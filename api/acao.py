import json
import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import jev_core as jc


def api_acao(body):
    mes = body.get("mes")
    if not isinstance(mes, str) or mes not in jc.meses_disponiveis():
        raise ValueError(f"Mês inválido: {mes}")
    return jc.gerar_acao(
        mes, body.get("tipo"), body.get("pedido"),
        arquivo=body.get("arquivo") or "",
        decisao_jev=body.get("decisao_jev"),
    )


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
            dados = api_acao(body)
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
