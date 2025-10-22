# api/index.py  — Vercel Python Functions 用（Flask/WSGI）
import os
import re
import subprocess
from flask import Flask, jsonify, request

app = Flask(__name__)

@app.get("/")
def root():
    # ベースURL確認用
    return jsonify(ok=True, base="/api/index")

@app.get("/health")
def health():
    return jsonify(ok=True)

@app.get("/serp/average")
def serp_average():
    # クエリ取得
    keyword = request.args.get("keyword")
    num = int(request.args.get("num", 10))
    lang = request.args.get("lang", "ja")
    country = request.args.get("country", "jp")

    if not keyword:
        return jsonify(error="missing keyword"), 400

    env = os.environ.copy()

    def run_cmd(py):
        return subprocess.run(
            [py, "serp_charcount.py", keyword, "--num", str(num),
             "--lang", lang, "--country", country, "--csv", "/tmp/out.csv"],
            capture_output=True, text=True, env=env, timeout=90
        )

    # python3 -> だめなら python
    result = run_cmd("python3")
    if result.returncode != 0 or not result.stdout:
        result = run_cmd("python")

    output = (result.stdout or "") + "\n" + (result.stderr or "")
    m = re.search(r"Average.*?:\s*(\d+)\s+chars", output)
    avg = int(m.group(1)) if m else None

    return jsonify(
        keyword=keyword,
        sampled=num,
        average_non_zero=avg,
        raw_output=output.strip()[:5000],
    )
