import json
import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import jev_core as jc


def api_filtros():
    meses = jc.meses_disponiveis()
    lojas = {l["id_loja"]: l for l in jc.supabase("lojas")}
    return {
        "meses": [{"valor": m, "rotulo": jc.nome_mes(m)} for m in meses],
        "regioes": sorted({l["regiao"] for l in lojas.values()}),
        "lojas": [{"id": i, "nome": l["loja"], "regiao": l["regiao"]} for i, l in sorted(lojas.items())],
    }


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            dados = api_filtros()
            corpo = json.dumps(dados, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
        except Exception as e:
            corpo = json.dumps({"erro": str(e)}, ensure_ascii=False).encode("utf-8")
            self.send_response(502)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(corpo)
