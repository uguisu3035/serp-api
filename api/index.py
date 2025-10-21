# api/index.py  — まずは疎通最優先の最小構成
from fastapi import FastAPI, Query
import subprocess, os, re

app = FastAPI(title="SERP Average API", version="1.0.0")

@app.get("/health")
def health():
    return {"ok": True}

@app.get("/serp/average")
def serp_average(
    keyword: str = Query(..., description="検索キーワード"),
    num: int = 10,
    lang: str = "ja",
    country: str = "jp",
):
    # Vercelの環境変数（GOOGLE_API_KEY / GOOGLE_CSE_ID）を利用
    env = os.environ.copy()

    def run_cmd(py):
        return subprocess.run(
            [py, "serp_charcount.py", keyword, "--num", str(num),
             "--lang", lang, "--country", country, "--csv", "/tmp/out.csv"],
            capture_output=True, text=True, env=env, timeout=90
        )

    # python3 → ダメなら python
    result = run_cmd("python3")
    if result.returncode != 0 or not result.stdout:
        result = run_cmd("python")

    output = (result.stdout or "") + "\n" + (result.stderr or "")
    m = re.search(r"Average.*?:\s*(\d+)\s+chars", output)
    avg = int(m.group(1)) if m else None

    return {
        "keyword": keyword,
        "sampled": num,
        "average_non_zero": avg,
        "raw_output": output.strip()[:5000]
    }
