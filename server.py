import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import jev_core as jc

HTML = jc.ROOT / "dashboard" / "index.html"
HOST, PORTA = "127.0.0.1", 8000


class Erro400(Exception):
    pass


# ---------- formatação ----------

def dinheiro(v):
    if abs(v) >= 1e6:
        return f"R$ {jc.fmt(v / 1e6, 1)} mi"
    if abs(v) >= 1e3:
        return f"R$ {jc.fmt(v / 1e3, 0)} mil"
    return f"R$ {jc.fmt(v, 0)}"


def pct(frac):
    return jc.pct(frac, 1)


def nps_txt(v):
    return jc.fmt(v, 0) if float(v).is_integer() else jc.fmt(v, 1)


def mes_curto(mes):
    ano, m = mes.split("-")
    return f"{jc.NOMES_MESES[int(m) - 1][:3]}/{ano[2:]}"


def variacao(atual, anterior, tipo, mes_ant, maior_melhor=True):
    if anterior is None:
        return None
    d = atual - anterior
    if abs(d) < 1e-9:
        return {"texto": f"estável vs {jc.nome_mes(mes_ant)}", "direcao": "igual", "bom": None}
    if tipo == "pct":
        texto = f"{jc.fmt(abs(atual / anterior - 1) * 100, 1)}%"
    elif tipo == "pp":
        texto = f"{jc.fmt(abs(d) * 100, 1)} p.p."
    elif tipo == "pts":
        texto = f"{jc.fmt(abs(d), 1)} pts"
    else:
        texto = jc.fmt(abs(d), 0)
    return {"texto": f"{texto} vs {jc.nome_mes(mes_ant)}", "direcao": "sobe" if d > 0 else "desce",
            "bom": (d > 0) == maior_melhor}


# ---------- API ----------

def contexto():
    return jc.meses_disponiveis(), {l["id_loja"]: l for l in jc.supabase("lojas")}


def api_filtros():
    meses, lojas = contexto()
    return {
        "meses": [{"valor": m, "rotulo": jc.nome_mes(m)} for m in meses],
        "regioes": sorted({l["regiao"] for l in lojas.values()}),
        "lojas": [{"id": i, "nome": l["loja"], "regiao": l["regiao"]} for i, l in sorted(lojas.items())],
    }


def api_dados(q):
    meses, lojas = contexto()
    mes = q.get("mes") or meses[-1]
    if mes not in meses:
        raise Erro400(f"Mês inválido: {mes}. Disponíveis: {', '.join(meses)}")
    regiao, loja = q.get("regiao") or None, q.get("loja") or None
    if regiao and regiao not in {l["regiao"] for l in lojas.values()}:
        raise Erro400(f"Região inválida: {regiao}")
    if loja:
        if loja not in lojas:
            raise Erro400(f"Loja inválida: {loja}")
        if regiao and lojas[loja]["regiao"] != regiao:
            raise Erro400(f"A loja {loja} não pertence à região {regiao}")
        regiao = lojas[loja]["regiao"]
    ant = jc.mes_anterior(mes, meses)

    por_mes = {}
    for p in jc.supabase("performance_mensal"):
        por_mes.setdefault(p["mes"], []).append(p)
    pv = jc.supabase("pos_venda", jc.intervalo_mes(mes), select="id_loja")
    pv0 = jc.supabase("pos_venda", jc.intervalo_mes(ant), select="id_loja") if ant else None

    def no_escopo(id_loja):
        if loja:
            return id_loja == loja
        return not regiao or lojas[id_loja]["regiao"] == regiao

    atual, prev = por_mes[mes], por_mes.get(ant, [])
    esc = [p for p in atual if no_escopo(p["id_loja"])]
    esc0 = [p for p in prev if no_escopo(p["id_loja"])]
    a, a0, rede = jc.agregado(esc), (jc.agregado(esc0) if esc0 else None), jc.agregado(atual)
    oc = sum(1 for o in pv if no_escopo(o["id_loja"]))
    oc0 = sum(1 for o in pv0 if no_escopo(o["id_loja"])) if pv0 is not None else None
    filtrado = bool(regiao or loja)

    if loja:
        exibindo, escopo_txt = f"Loja {loja} · {lojas[loja]['loja']} ({regiao})", f"a loja {loja}"
    elif regiao:
        exibindo, escopo_txt = f"Região {regiao}", f"a região {regiao}"
    else:
        exibindo, escopo_txt = "Rede inteira (40 lojas)", "a rede"

    big = [
        {"rotulo": "Faturamento", "valor": dinheiro(a["faturamento"]),
         "var": variacao(a["faturamento"], a0 and a0["faturamento"], "pct", ant),
         "contexto": f"Meta {dinheiro(a['meta'])}"},
        {"rotulo": "% da Meta", "valor": pct(a["atingimento"]),
         "var": variacao(a["atingimento"], a0 and a0["atingimento"], "pp", ant),
         "contexto": f"Referência 100% · rede {pct(rede['atingimento'])}" if filtrado else "Referência 100%"},
        {"rotulo": "NPS médio", "valor": nps_txt(a["nps"]),
         "var": variacao(a["nps"], a0 and a0["nps"], "pts", ant),
         "contexto": f"NPS da rede {nps_txt(rede['nps'])}" if filtrado else "Média das 40 lojas"},
        {"rotulo": "Ocorrências de pós-venda", "valor": jc.fmt(oc, 0),
         "var": variacao(oc, oc0, "int", ant, maior_melhor=False),
         "contexto": f"Rede {jc.fmt(len(pv), 0)} no mês" if filtrado else "Todas as lojas"},
    ]

    # gráfico 1: regiões
    reg = sorted(jc.por_regiao(atual, lojas).items(), key=lambda kv: kv[1]["atingimento"])
    foco_r = regiao or reg[0][0]
    v = dict(reg)[foco_r]["atingimento"]
    graf_regioes = {
        "titulo": f"{foco_r} ficou {jc.fmt(abs(v - 1) * 100, 1)} p.p. {'abaixo' if v < 1 else 'acima'} da meta",
        "rotulos": [r for r, _ in reg],
        "valores": [round(x["atingimento"] * 100, 2) for _, x in reg],
        "textos": [pct(x["atingimento"]) for _, x in reg],
        "foco": foco_r,
    }

    # gráfico 2: evolução
    serie = [jc.agregado([p for p in por_mes[m] if no_escopo(p["id_loja"])]) for m in meses]
    graf_evolucao = {
        "titulo": (f"Em {jc.nome_mes(mes)}, {escopo_txt} faturou {jc.fmt(abs(a['atingimento'] - 1) * 100, 1)}% "
                   f"{'abaixo' if a['atingimento'] < 1 else 'acima'} da meta"),
        "rotulos": [mes_curto(m) for m in meses],
        "faturamento": [round(s["faturamento"], 2) for s in serie],
        "meta": [round(s["meta"], 2) for s in serie],
        "textos_faturamento": [dinheiro(s["faturamento"]) for s in serie],
        "textos_meta": [dinheiro(s["meta"]) for s in serie],
        "indice": meses.index(mes),
    }

    # gráfico 3: lojas
    cand = sorted((p for p in atual if not regiao or lojas[p["id_loja"]]["regiao"] == regiao),
                  key=lambda p: jc.num(p["atingimento_meta"]))
    top = cand[:10]
    if loja and loja not in {p["id_loja"] for p in top}:
        top = top[:9] + [p for p in cand if p["id_loja"] == loja]
    top.sort(key=lambda p: jc.num(p["atingimento_meta"]))
    onde = f"no {regiao}" if regiao else "na rede"
    if loja:
        pos = [p["id_loja"] for p in cand].index(loja) + 1
        at_l = jc.num(next(p for p in cand if p["id_loja"] == loja)["atingimento_meta"])
        titulo3 = f"{loja} atingiu {pct(at_l)} da meta: {pos}ª pior de {len(cand)} lojas {onde}"
    else:
        p0 = top[0]
        titulo3 = (f"{p0['id_loja']} {lojas[p0['id_loja']]['loja']} tem o pior atingimento {onde}: "
                   f"{pct(jc.num(p0['atingimento_meta']))}")
    graf_lojas = {
        "titulo": titulo3,
        "ids": [p["id_loja"] for p in top],
        "rotulos": [f"{p['id_loja']} · {lojas[p['id_loja']]['loja']}" for p in top],
        "valores": [round(jc.num(p["atingimento_meta"]) * 100, 2) for p in top],
        "textos": [pct(jc.num(p["atingimento_meta"])) for p in top],
        "foco": loja or top[0]["id_loja"],
    }

    return {
        "mes": mes, "rotulo_mes": jc.nome_mes(mes), "regiao": regiao or "", "loja": loja or "",
        "exibindo": f"{exibindo} · {jc.nome_mes(mes)}",
        "big": big, "graf_regioes": graf_regioes, "graf_evolucao": graf_evolucao, "graf_lojas": graf_lojas,
    }


def sinal_pct(v):
    return f"{'+' if v >= 0 else '−'}{jc.fmt(abs(v) * 100, 1)}%"


def texto_prioridade(p, mes):
    ant = jc.mes_anterior(mes, jc.meses_disponiveis())
    if p.get("var_faturamento") is None:
        destaque = "Sem mês anterior para comparar"
        detalhe = f"{pct(p['atingimento'])} da meta"
    else:
        mq = p["maior_queda"]
        destaque = (f"▼ {mq['fator']} {sinal_pct(mq['variacao'])} vs {jc.nome_mes(ant)}" if mq
                    else f"Sem queda em visitas, conversão ou ticket vs {jc.nome_mes(ant)}")
        detalhe = f"Faturamento {sinal_pct(p['var_faturamento'])} · {pct(p['atingimento'])} da meta"
    return dict(p, destaque=destaque, detalhe=detalhe)


def api_jev(body):
    mes = body.get("mes")
    if not isinstance(mes, str) or mes not in jc.meses_disponiveis():
        raise Erro400(f"Mês inválido: {mes}")
    r = jc.analisar_mes(mes)
    risco = r["risco"]
    noul = r["revisao_humana"]
    probs = sorted(r["probabilidades"].items(), key=lambda kv: -kv[1])
    return {
        "mes": mes, "rotulo_mes": jc.nome_mes(mes),
        "causa": r["causa"], "score": r["score"], "etiqueta": r["etiqueta"],
        "probabilidades": [{"causa": c, "p": p, "texto": f"{jc.fmt(p * 100, 0)}%"} for c, p in probs],
        "risco": {"score": risco["score"], "rotulo": risco["legend"][str(round(risco["score"]))],
                  "texto": jc.fmt(risco["score"], 2)},
        "revisao_humana": {"noul": noul, "texto": f"{jc.fmt(noul * 100, 0)}%", "recomendada": noul >= 0.5},
        "prioridades": [texto_prioridade(p, mes) for p in r["prioridades"]],
        "modelo": r["modelo"], "arquivo": r["arquivo"],
    }


def api_acao(body):
    mes = body.get("mes")
    if not isinstance(mes, str) or mes not in jc.meses_disponiveis():
        raise Erro400(f"Mês inválido: {mes}")
    try:
        return jc.gerar_acao(mes, body.get("tipo"), body.get("pedido"), body.get("arquivo") or "")
    except ValueError as e:
        raise Erro400(str(e)) from None


# ---------- servidor ----------

class Handler(BaseHTTPRequestHandler):
    def _enviar(self, codigo, corpo, tipo="application/json; charset=utf-8"):
        dados = corpo if isinstance(corpo, bytes) else json.dumps(corpo, ensure_ascii=False).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(dados)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(dados)

    def _rodar(self, fn):
        try:
            self._enviar(200, fn())
        except Erro400 as e:
            self._enviar(400, {"erro": str(e)})
        except Exception as e:
            self._enviar(502, {"erro": f"Falha ao consultar o serviço externo: {e}"})

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if u.path in ("/", "/index.html"):
            self._enviar(200, HTML.read_bytes(), "text/html; charset=utf-8")
        elif u.path == "/api/meses":
            self._rodar(jc.meses_disponiveis)
        elif u.path == "/api/filtros":
            self._rodar(api_filtros)
        elif u.path == "/api/dados":
            self._rodar(lambda: api_dados(q))
        else:
            self._enviar(404, {"erro": "Não encontrado"})

    def do_POST(self):
        u = urlparse(self.path)
        if u.path not in ("/api/jev", "/api/acao"):
            return self._enviar(404, {"erro": "Não encontrado"})
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            if not isinstance(body, dict):
                raise ValueError
        except ValueError:
            return self._enviar(400, {"erro": "Corpo da requisição deve ser um JSON válido"})
        self._rodar(lambda: api_jev(body) if u.path == "/api/jev" else api_acao(body))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    print(f"Dashboard em http://localhost:{PORTA}")
    ThreadingHTTPServer((HOST, PORTA), Handler).serve_forever()
