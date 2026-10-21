import json
import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import jev_core as jc


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            dados = jc.meses_disponiveis()
            corpo = json.dumps(dados, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
        except Exception as e:
            corpo = json.dumps({"erro": str(e)}, ensure_ascii=False).encode("utf-8")
            self.send_response(502)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(corpo)
