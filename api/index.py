# api/index.py --- 最小疎通テスト用
from fastapi import FastAPI

app = FastAPI(title="Ping API", version="1.0.0")

@app.get("/")
def root():
    return {"ok": True, "base": "/api/index"}

@app.get("/health")
def health():
    return {"ok": True}
