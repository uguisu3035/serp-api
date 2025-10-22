# api/serp/average.py  — Vercel Python最小形（BaseHTTPRequestHandler）
from http.server import BaseHTTPRequestHandler
import os, re, subprocess, urllib.parse, json

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        # クエリを取得
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        keyword = qs.get("keyword", [None])[0]
        num = int(qs.get("num", ["10"])[0])
        lang = qs.get("lang", ["ja"])[0]
        country = qs.get("country", ["jp"])[0]

        if not keyword:
            self._json(400, {"error": "missing keyword"})
            return

        env = os.environ.copy()

        def run(py):
            return subprocess.run(
                [py, "serp_charcount.py", keyword, "--num", str(num),
                 "--lang", lang, "--country", country, "--csv", "/tmp/out.csv"],
                capture_output=True, text=True, env=env, timeout=90
            )

        # python3 → ダメなら python
        r = run("python3")
        if r.returncode != 0 or (not r.stdout and not r.stderr):
            r = run("python")

        output = (r.stdout or "") + "\n" + (r.stderr or "")
        m = re.search(r"Average.*?:\s*(\d+)\s+chars", output)
        avg = int(m.group(1)) if m else None

        self._json(200, {
            "keyword": keyword,
            "sampled": num,
            "average_non_zero": avg,
            "raw_output": output[:5000]
        })

    def _json(self, status: int, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
