# app.py
from fastapi import FastAPI
import subprocess
import json

app = FastAPI()

@app.get("/serp/average")
def get_serp_average(keyword: str, num: int = 10, lang: str = "ja", country: str = "jp"):
    """Run your serp_charcount.py script and return average as JSON"""
    try:
        # 実際にあなたのPythonスクリプトを呼び出す
        result = subprocess.run(
            ["python", "serp_charcount.py", keyword, "--num", str(num),
             "--lang", lang, "--country", country, "--csv", "temp.csv"],
            capture_output=True, text=True
        )
        output = result.stdout
        # 平均文字数の行を探す
        avg_line = [line for line in output.splitlines() if "Average" in line]
        avg_value = None
        if avg_line:
            avg_value = int("".join([ch for ch in avg_line[0] if ch.isdigit()]) or 0)
        return {"keyword": keyword, "average_non_zero": avg_value, "raw_output": output}
    except Exception as e:
        return {"error": str(e)}
