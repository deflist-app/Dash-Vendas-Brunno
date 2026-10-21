import json
import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import jev_core as jc


def sinal_pct(v):
    return f"{'+' if v >= 0 else '−'}{jc.fmt(abs(v) * 100, 1)}%"


def texto_prioridade(p, mes):
    ant = jc.mes_anterior(mes, jc.meses_disponiveis())
    if p.get("var_faturamento") is None:
        destaque = "Sem mês anterior para comparar"
        detalhe = f"{jc.pct(p['atingimento'], 1)} da meta"
    else:
        mq = p["maior_queda"]
        destaque = (f"▼ {mq['fator']} {sinal_pct(mq['variacao'])} vs {jc.nome_mes(ant)}" if mq
                    else f"Sem queda em visitas, conversão ou ticket vs {jc.nome_mes(ant)}")
        detalhe = f"Faturamento {sinal_pct(p['var_faturamento'])} · {jc.pct(p['atingimento'], 1)} da meta"
    return dict(p, destaque=destaque, detalhe=detalhe)


def api_jev(body):
    mes = body.get("mes")
    if not isinstance(mes, str) or mes not in jc.meses_disponiveis():
        raise ValueError(f"Mês inválido: {mes}")
    r = jc.analisar_mes(mes)
    risco = r["risco"]
    probs = sorted(r["probabilidades"].items(), key=lambda kv: -kv[1])
    registro = r.pop("_registro", None)
    return {
        "mes": mes, "rotulo_mes": jc.nome_mes(mes),
        "causa": r["causa"], "score": r["score"], "etiqueta": r["etiqueta"],
        "probabilidades": [{"causa": c, "p": p, "texto": f"{jc.fmt(p * 100, 0)}%"} for c, p in probs],
        "risco": {"score": risco["score"], "rotulo": risco["legend"][str(round(risco["score"]))],
                  "texto": jc.fmt(risco["score"], 2)},
        "revisao_humana": {"noul": r["revisao_humana"], "texto": f"{jc.fmt(r['revisao_humana'] * 100, 0)}%",
                           "recomendada": r["revisao_humana"] >= 0.5},
        "prioridades": [texto_prioridade(p, mes) for p in r["prioridades"]],
        "modelo": r["modelo"], "arquivo": r["arquivo"],
        "decisao_jev": registro,
    }


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            if not isinstance(body, dict):
                raise ValueError
        except (ValueError, json.JSONDecodeError):
            corpo = json.dumps({"erro": "Corpo da requisição deve ser um JSON válido"}, ensure_ascii=False).encode("utf-8")
            self.send_response(400)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(corpo)
            return
        try:
            dados = api_jev(body)
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
