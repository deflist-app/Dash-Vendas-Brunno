import json
import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import jev_core as jc


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


def api_dados(q):
    meses = jc.meses_disponiveis()
    lojas = {l["id_loja"]: l for l in jc.supabase("lojas")}
    mes = q.get("mes") or meses[-1]
    if mes not in meses:
        raise ValueError(f"Mês inválido: {mes}. Disponíveis: {', '.join(meses)}")
    regiao, loja = q.get("regiao") or None, q.get("loja") or None
    if regiao and regiao not in {l["regiao"] for l in lojas.values()}:
        raise ValueError(f"Região inválida: {regiao}")
    if loja:
        if loja not in lojas:
            raise ValueError(f"Loja inválida: {loja}")
        if regiao and lojas[loja]["regiao"] != regiao:
            raise ValueError(f"A loja {loja} não pertence à região {regiao}")
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


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            dados = api_dados(q)
            corpo = json.dumps(dados, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
        except ValueError as e:
            corpo = json.dumps({"erro": str(e)}, ensure_ascii=False).encode("utf-8")
            self.send_response(400)
        except Exception as e:
            corpo = json.dumps({"erro": f"Falha ao consultar o serviço externo: {e}"}, ensure_ascii=False).encode("utf-8")
            self.send_response(502)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(corpo)
