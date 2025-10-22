# api/hello.py  ← Vercel公式の最小形（handler = BaseHTTPRequestHandler）
from http.server import BaseHTTPRequestHandler

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type","application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(b'{"ok": true, "route": "/api/hello"}')
        return
