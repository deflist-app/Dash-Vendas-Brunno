import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime
from pathlib import Path

import os as _os

ROOT = Path(__file__).resolve().parent
RUNS = Path("/tmp/runs") if _os.environ.get("VERCEL") else ROOT / "runs"
JEV_URL = "https://openrouter.ai/api/alpha/decisions"
JEV_MODEL = "typesafe/jev-1.13"
TIPOS_POS_VENDA = ["Produto", "Entrega", "Troca", "Atendimento", "Disponibilidade"]
NOMES_MESES = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho",
               "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]

QUESTIONS = {
    "causa_principal": {
        "type": "choice",
        "instructions": (
            "Com base no dossiê da rede inteira neste mês, qual é a causa mais provável do resultado? "
            "Pequenas oscilações em 1 ou 2 lojas são normais e não definem a causa da rede. "
            "Só aponte uma causa quando houver sinais consistentes nos números E nos textos "
            "(comentários dos gerentes, reviews e pós-venda)."
        ),
        "criteria": {
            "Estoque": "Ruptura, falta de produto, atraso de reposição limitando vendas",
            "Equipe": "Falta de pessoal, rotatividade, desfalque ou treinamento insuficiente",
            "Atendimento": "Mau atendimento, demora, reclamações de tratamento ao cliente",
            "Demanda": "Menos clientes/visitas por fatores de mercado, sazonalidade ou concorrência",
            "Preço": "Preço acima do mercado, promoções da concorrência, sensibilidade a preço",
            "Sem problema relevante": "Rede perto da meta, sem região com queda forte, comentários sem queixas",
        },
    },
    "risco_rede": {
        "type": "score",
        "instructions": "Qual o nível de risco para o resultado da rede, considerando o dossiê deste mês?",
        "criteria": ["Muito baixo", "Baixo", "Moderado", "Alto", "Muito alto"],
    },
    "revisao_humana": {
        "type": "noul",
        "instructions": (
            "Os sinais deste mês são ambíguos ou contraditórios a ponto de exigir que um analista "
            "confirme a causa antes de agir? Avalie apenas a incerteza sobre a causa, não a gravidade do resultado."
        ),
        "criteria": {
            "true": "Números e textos apontam para causas diferentes ou não sustentam uma causa clara",
            "false": "Números e textos convergem para a mesma causa, mesmo que o resultado seja grave",
        },
    },
}


def _carregar_env():
    import os
    env = dict(os.environ)
    env_file = ROOT / ".env"
    if env_file.is_file():
        for linha in env_file.read_text(encoding="utf-8").splitlines():
            if "=" in linha and not linha.lstrip().startswith("#"):
                chave, valor = linha.split("=", 1)
                env.setdefault(chave.strip(), valor.strip())
    return env


ENV = _carregar_env()


# ---------- Supabase ----------

def supabase(tabela, filtros=(), select="*"):
    base = ENV["SUPABASE_URL"].rstrip("/") + f"/rest/v1/{tabela}"
    chave = ENV["SUPABASE_KEY"]
    headers = {"apikey": chave, "Authorization": f"Bearer {chave}"}
    linhas, offset, limite = [], 0, 1000
    while True:
        params = [("select", select), *filtros, ("limit", str(limite)), ("offset", str(offset))]
        req = urllib.request.Request(base + "?" + urllib.parse.urlencode(params), headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            lote = json.loads(resp.read())
        linhas += [{k.lower(): v for k, v in linha.items()} for linha in lote]
        if len(lote) < limite:
            return linhas
        offset += limite


def meses_disponiveis():
    return sorted({l["mes"] for l in supabase("performance_mensal", select="mes")})


def intervalo_mes(mes):
    ano, m = map(int, mes.split("-"))
    ano2, m2 = (ano + 1, 1) if m == 12 else (ano, m + 1)
    return [("data", f"gte.{mes}-01"), ("data", f"lt.{ano2:04d}-{m2:02d}-01")]


def dados_mes(mes):
    return {
        "perf": supabase("performance_mensal", [("mes", f"eq.{mes}")]),
        "relatorios": supabase("relatorio_gestores", [("mes", f"eq.{mes}")]),
        "reviews": supabase("reviews_clientes", intervalo_mes(mes)),
        "pos_venda": supabase("pos_venda", intervalo_mes(mes)),
    }


def mes_anterior(mes, meses):
    i = meses.index(mes)
    return meses[i - 1] if i > 0 else None


# ---------- formatação e cálculos ----------

def num(v):
    return float(v) if v not in (None, "") else None


def fmt(v, casas=1):
    return f"{v:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def brl(v):
    if abs(v) >= 1e6:
        return f"R$ {fmt(v / 1e6, 2)} mi"
    return f"R$ {fmt(v / 1e3, 1)} mil"


def pct(frac, casas=1):
    return f"{fmt(frac * 100, casas)}%"


def pp(delta):
    return f"{'+' if delta >= 0 else ''}{fmt(delta * 100, 1)} p.p."


def var_pct(atual, anterior):
    d = atual / anterior - 1
    return f"{'+' if d >= 0 else ''}{fmt(d * 100, 1)}%"


def nome_mes(mes):
    ano, m = mes.split("-")
    return f"{NOMES_MESES[int(m) - 1]}/{ano}"


def agregado(perf):
    fat = sum(num(p["faturamento"]) for p in perf)
    meta = sum(num(p["meta"]) for p in perf)
    nps = sum(num(p["nps"]) for p in perf) / len(perf)
    return {"faturamento": fat, "meta": meta, "atingimento": fat / meta, "nps": nps}


def por_regiao(perf, lojas):
    grupos = {}
    for p in perf:
        grupos.setdefault(lojas[p["id_loja"]]["regiao"], []).append(p)
    return {r: agregado(ps) for r, ps in grupos.items()}


def piores_lojas(perf, n=5):
    return sorted(perf, key=lambda p: num(p["atingimento_meta"]))[:n]


def etiqueta(score):
    if score >= 70:
        return "Agir"
    if score >= 40:
        return "Confirmar"
    return "Investigar"


# ---------- dossiê ----------

def montar_dossie(mes):
    meses = meses_disponiveis()
    if mes not in meses:
        raise ValueError(f"Mês {mes} não existe no banco. Disponíveis: {', '.join(meses)}")
    ant = mes_anterior(mes, meses)
    lojas = {l["id_loja"]: l for l in supabase("lojas")}
    atual = dados_mes(mes)
    prev = dados_mes(ant) if ant else None
    ref = f" vs {nome_mes(ant)}" if ant else ""
    b = [f"DOSSIÊ DA REDE — {nome_mes(mes)} (40 lojas, 5 regiões)"]

    # 1. rede
    r = agregado(atual["perf"])
    b.append("\n1. INDICADORES DA REDE" + ref)
    if prev:
        r0 = agregado(prev["perf"])
        b.append(f"- Faturamento: {brl(r['faturamento'])} ({var_pct(r['faturamento'], r0['faturamento'])})")
        b.append(f"- Atingimento da meta: {pct(r['atingimento'])} ({pp(r['atingimento'] - r0['atingimento'])})")
        b.append(f"- NPS médio: {fmt(r['nps'], 1)} (antes {fmt(r0['nps'], 1)})")
    else:
        b.append(f"- Faturamento: {brl(r['faturamento'])}")
        b.append(f"- Atingimento da meta: {pct(r['atingimento'])}")
        b.append(f"- NPS médio: {fmt(r['nps'], 1)}")

    # 2. regiões
    reg = por_regiao(atual["perf"], lojas)
    reg0 = por_regiao(prev["perf"], lojas) if prev else {}
    b.append("\n2. POR REGIÃO (do pior para o melhor atingimento)")
    for nome, v in sorted(reg.items(), key=lambda kv: kv[1]["atingimento"]):
        linha = f"- {nome}: atingimento {pct(v['atingimento'])}, NPS {fmt(v['nps'], 1)}"
        if nome in reg0:
            linha += f", variação do atingimento {pp(v['atingimento'] - reg0[nome]['atingimento'])}"
        b.append(linha)

    # 3. piores lojas
    piores = piores_lojas(atual["perf"])
    ids = [p["id_loja"] for p in piores]
    perf0 = {p["id_loja"]: p for p in prev["perf"]} if prev else {}
    b.append("\n3. AS 5 LOJAS COM PIOR ATINGIMENTO DA META")
    for p in piores:
        l = lojas[p["id_loja"]]
        linha = (f"- {p['id_loja']} {l['loja']} ({l['regiao']}): atingimento {pct(num(p['atingimento_meta']))}, "
                 f"conversão {pct(num(p['conversao']), 2)}")
        q = perf0.get(p["id_loja"])
        if q:
            linha += f" ({pp(num(p['conversao']) - num(q['conversao']))})"
        linha += f", visitas {fmt(num(p['visitas']), 0)}"
        if q:
            linha += f" ({var_pct(num(p['visitas']), num(q['visitas']))})"
        linha += f", NPS {fmt(num(p['nps']), 0)}"
        b.append(linha)

    # 4. pós-venda
    c = Counter(o["tipo_ocorrencia"] for o in atual["pos_venda"])
    c0 = Counter(o["tipo_ocorrencia"] for o in prev["pos_venda"]) if prev else None
    b.append("\n4. PÓS-VENDA DA REDE" + ref)
    b.append(f"- Total: {len(atual['pos_venda'])}" + (f" (antes {len(prev['pos_venda'])})" if prev else ""))
    for t in TIPOS_POS_VENDA:
        b.append(f"- {t}: {c[t]}" + (f" (antes {c0[t]})" if c0 is not None else ""))

    # 5. comentários dos gerentes
    b.append("\n5. COMENTÁRIOS DOS GERENTES DESSAS 5 LOJAS")
    rel = {x["id_loja"]: x["comentario_gerente"] for x in atual["relatorios"]}
    for i in ids:
        b.append(f"- {i}: {rel.get(i, '(sem comentário)')}")

    # 6. reviews
    b.append("\n6. AS 10 AVALIAÇÕES DE MENOR NOTA DESSAS 5 LOJAS")
    revs = sorted((x for x in atual["reviews"] if x["id_loja"] in ids), key=lambda x: int(x["nota"]))[:10]
    for x in revs:
        b.append(f"- {x['id_loja']} (nota {x['nota']}, {x['canal']}): {x['comentario']}")
    if not revs:
        b.append("- (sem avaliações)")

    # 7. ocorrências
    b.append("\n7. OCORRÊNCIAS DE PÓS-VENDA DESSAS 5 LOJAS (até 8)")
    ocs = sorted((o for o in atual["pos_venda"] if o["id_loja"] in ids), key=lambda o: o["data"])[:8]
    for o in ocs:
        b.append(f"- {o['id_loja']} [{o['tipo_ocorrencia']}]: {o['descricao']}")
    if not ocs:
        b.append("- (sem ocorrências)")

    prioridades = [{
        "id_loja": p["id_loja"],
        "loja": lojas[p["id_loja"]]["loja"],
        "regiao": lojas[p["id_loja"]]["regiao"],
        "gerente": lojas[p["id_loja"]]["gerente"],
        "atingimento": num(p["atingimento_meta"]),
        **decompor_faturamento(p, perf0.get(p["id_loja"])),
    } for p in piores[:3]]
    return "\n".join(b), prioridades


def decompor_faturamento(p, q):
    """Faturamento = visitas × conversão × ticket médio; aponta o fator com maior queda vs mês anterior."""
    if not q:
        return {"var_faturamento": None, "maior_queda": None}
    fatores = {
        "Visitas": num(p["visitas"]) / num(q["visitas"]) - 1,
        "Conversão": num(p["conversao"]) / num(q["conversao"]) - 1,
        "Ticket médio": num(p["ticket_medio"]) / num(q["ticket_medio"]) - 1,
    }
    nome, var = min(fatores.items(), key=lambda kv: kv[1])
    return {
        "var_faturamento": num(p["faturamento"]) / num(q["faturamento"]) - 1,
        "maior_queda": {"fator": nome, "variacao": var} if var < 0 else None,
        "fatores": fatores,
    }


# ---------- OpenRouter ----------

def _post(url, body):
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {ENV['OPENROUTER_API_KEY']}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"OpenRouter devolveu {e.code}: {e.read().decode('utf-8', 'replace')}") from None


def analisar_mes(mes):
    dossie, prioridades = montar_dossie(mes)
    enviado = {"model": JEV_MODEL, "state": dossie, "questions": QUESTIONS}
    recebido = _post(JEV_URL, enviado)

    RUNS.mkdir(exist_ok=True)
    arquivo = RUNS / f"jev_{mes}_{datetime.now():%Y%m%d_%H%M%S}.json"
    registro = {"mes": mes, "enviado": enviado, "recebido": recebido, "prioridades": prioridades}
    try:
        arquivo.write_text(json.dumps(registro, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass

    return dict(resumir_decisao(recebido), mes=mes, prioridades=prioridades,
                arquivo=f"runs/{arquivo.name}", _registro=registro)


def resumir_decisao(recebido):
    ans = recebido["answers"]
    causa = ans["causa_principal"]["choice"]
    score = round(ans["causa_principal"]["probabilities"][causa] * 100)
    return {
        "causa": causa,
        "score": score,
        "etiqueta": etiqueta(score),
        "probabilidades": ans["causa_principal"]["probabilities"],
        "confianca": ans["causa_principal"].get("confidence"),
        "risco": ans["risco_rede"],
        "revisao_humana": ans["revisao_humana"]["noul"],
        "modelo": recebido.get("model"),
        "usage": recebido.get("usage"),
    }


# ---------- Haiku ----------

HAIKU_URL = "https://openrouter.ai/api/v1/chat/completions"
HAIKU_MODEL = "anthropic/claude-haiku-4.5"
TIPOS_ACAO = ("gerente", "diretoria", "livre")
HAIKU_SYSTEM = (
    "Você é um redator de comunicação executiva de uma rede varejista. Escreva em português do Brasil, "
    "com tom profissional e direto. A decisão abaixo foi tomada pelo JEV e é um FATO: não altere a causa nem o score, "
    "não invente números. Não reinterprete, não questione e não contradiga a decisão. "
    "Use somente os números fornecidos. Sem emojis. Escreva em texto simples, sem Markdown: nada de **, #, tabelas ou ---. "
    "O texto deve ficar pronto para colar em e-mail ou WhatsApp."
)
TAREFAS = {
    "gerente": ("Escreva uma mensagem ao gerente da loja prioritária nº 1, citando a causa apontada pelo JEV, "
                "o número que coloca a loja como prioridade, 2 a 3 ações práticas e um prazo de retorno. Até 150 palavras."),
    "diretoria": ("Escreva um resumo para a diretoria: um título de 1 linha e até 5 tópicos (resultado da rede, causa com Score "
                  "e etiqueta, risco, lojas prioritárias, próximo passo coerente com a etiqueta). Até 160 palavras."),
}


def ler_decisao(mes, arquivo):
    nome = Path(str(arquivo)).name
    if not (nome.startswith(f"jev_{mes}_") and nome.endswith(".json")):
        raise ValueError(f"Arquivo de decisão inválido para o mês {mes}: {arquivo}")
    caminho = RUNS / nome
    if not caminho.is_file():
        raise ValueError(f"Arquivo de decisão não encontrado: runs/{nome}")
    return nome, json.loads(caminho.read_text(encoding="utf-8"))


def fatos_haiku(mes, registro):
    d = resumir_decisao(registro["recebido"])
    risco = d["risco"]
    perf = supabase("performance_mensal", [("mes", f"eq.{mes}")])
    r = agregado(perf)
    ocorrencias = len(supabase("pos_venda", intervalo_mes(mes), select="id_loja"))
    linhas = [
        f"Mês analisado: {nome_mes(mes)} (rede inteira, 40 lojas)",
        f"Causa provável (JEV): {d['causa']}",
        f"Score de certeza: {d['score']} de 100",
        f"Etiqueta: {d['etiqueta']}",
        f"Risco da rede: {risco['legend'][str(round(risco['score']))]} ({fmt(risco['score'], 2)} numa escala de 0 a 4)",
        "Revisão humana: " + ("RECOMENDADA" if d["revisao_humana"] >= 0.5 else "NÃO necessária"),
        "Lojas prioritárias:",
    ]
    for i, p in enumerate(registro["prioridades"], 1):
        linhas.append(f"  {i}. {p['id_loja']} {p['loja']} ({p['regiao']}), gerente {p['gerente']}, "
                      f"atingimento da meta {pct(p['atingimento'])}")
    linhas += [
        "Números da rede no mês:",
        f"  Faturamento: {brl(r['faturamento'])} (meta {brl(r['meta'])})",
        f"  Atingimento da meta: {pct(r['atingimento'])}",
        f"  NPS médio: {fmt(r['nps'], 1)}",
        f"  Ocorrências de pós-venda: {ocorrencias}",
    ]
    return "\n".join(linhas)


def gerar_acao(mes, tipo, pedido, arquivo="", decisao_jev=None):
    if tipo not in TIPOS_ACAO:
        raise ValueError(f"Tipo inválido: {tipo}. Use gerente, diretoria ou livre.")
    if tipo == "livre":
        pedido = (pedido or "").strip()
        if not pedido:
            raise ValueError("Digite o pedido para o texto livre.")
        if len(pedido) > 1000:
            raise ValueError("O pedido deve ter no máximo 1000 caracteres.")
    if decisao_jev:
        nome, registro = "(inline)", decisao_jev
    else:
        nome, registro = ler_decisao(mes, arquivo)
    tarefa = pedido if tipo == "livre" else TAREFAS[tipo]
    user = (f"FATOS (decisão do JEV e números calculados):\n{fatos_haiku(mes, registro)}\n\n"
            f"TAREFA:\n{tarefa}\n\nLembrete: não altere a causa nem o score, não invente números.")
    enviado = {"model": HAIKU_MODEL, "max_tokens": 800, "temperature": 0.3,
               "messages": [{"role": "system", "content": HAIKU_SYSTEM}, {"role": "user", "content": user}]}
    recebido = _post(HAIKU_URL, enviado)

    RUNS.mkdir(exist_ok=True)
    saida = RUNS / f"haiku_{mes}_{tipo}_{datetime.now():%Y%m%d_%H%M%S_%f}.json"
    try:
        saida.write_text(json.dumps({"mes": mes, "tipo": tipo, "decisao_jev": f"runs/{nome}",
                                     "enviado": enviado, "recebido": recebido}, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass
    try:
        texto = recebido["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError, AttributeError):
        raise RuntimeError("Resposta do Haiku sem texto") from None
    if not texto:
        raise RuntimeError("O Haiku devolveu um texto vazio")
    return {"texto": texto, "modelo": recebido.get("model"), "arquivo": f"runs/{saida.name}", "decisao_jev": f"runs/{nome}"}


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    mes = sys.argv[1] if len(sys.argv) > 1 else meses_disponiveis()[-1]
    r = analisar_mes(mes)
    print(f"Mês: {nome_mes(mes)}")
    print(f"Causa: {r['causa']}")
    print(f"Score de certeza: {r['score']} -> {r['etiqueta']}")
    print(f"Probabilidades: {json.dumps(r['probabilidades'], ensure_ascii=False)}")
    print(f"Risco: {json.dumps(r['risco'], ensure_ascii=False)}")
    print(f"Revisão humana (noul): {r['revisao_humana']}")
    print("Prioridades: " + ", ".join(f"{p['id_loja']} ({p['regiao']}, {pct(p['atingimento'])})" for p in r["prioridades"]))
    u = r["usage"] or {}
    print(f"Modelo: {r['modelo']} · tokens: {u.get('input_tokens')} entrada / {u.get('output_tokens')} saída"
          f" · custo: US$ {u.get('cost', 0):.10f}".rstrip("0"))
    print(f"Gravado em: {r['arquivo']}")
