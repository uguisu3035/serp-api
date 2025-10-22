# api/serp/outline.py
from http.server import BaseHTTPRequestHandler
import os, json, urllib.parse, requests
from bs4 import BeautifulSoup

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
GOOGLE_CSE_ID = os.getenv("GOOGLE_CSE_ID")

def cse_search(q, num=10, lang="ja", country="jp"):
    url = "https://www.googleapis.com/customsearch/v1"
    params = {
        "key": GOOGLE_API_KEY,
        "cx": GOOGLE_CSE_ID,
        "q": q,
        "num": num,
        "hl": lang,
        "lr": f"lang_{lang}",
        "gl": country,
        "safe": "off"
    }
    r = requests.get(url, params=params, timeout=20)
    r.raise_for_status()
    items = r.json().get("items", []) or []
    return [it.get("link") for it in items if it.get("link")]

def fetch_headings(url):
    try:
        r = requests.get(
            url,
            timeout=20,
            headers={"User-Agent": "Mozilla/5.0 (SERP-Outline-Bot)"}
        )
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")
        title = (soup.title.string or "").strip() if soup.title and soup.title.string else ""

        hs = []
        for tag in soup.select("h1, h2, h3"):
            txt = tag.get_text(" ", strip=True)
            if txt:
                hs.append({"tag": tag.name.lower(), "text": txt})

        return {"url": url, "title": title, "headings": hs}
    except Exception:
        return {"url": url, "title": "", "headings": []}

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            parsed = urllib.parse.urlparse(self.path)
            qs = urllib.parse.parse_qs(parsed.query)
            keyword = (qs.get("keyword") or [None])[0]
            num = int((qs.get("num") or ["10"])[0])
            lang = (qs.get("lang") or ["ja"])[0]
            country = (qs.get("country") or ["jp"])[0]

            if not keyword:
                return self._json(400, {"error": "missing keyword"})

            urls = cse_search(keyword, num=num, lang=lang, country=country)
            sources = [fetch_headings(u) for u in urls]

            # 集計：頻出見出しテキスト、見出し数の平均
            from collections import Counter
            texts = [h["text"] for s in sources for h in s["headings"] if h["text"]]
            freq = Counter(texts)
            top_headings = [{"text": t, "count": c} for t, c in freq.most_common(30)]

            counts = [len(s["headings"]) for s in sources if s["headings"]]
            avg_count = round(sum(counts)/len(counts), 1) if counts else 0
            suggested = int(round(avg_count)) if avg_count else 10
            suggested = max(6, min(20, suggested))  # 6〜20に丸め

            return self._json(200, {
                "keyword": keyword,
                "sampled": len(urls),
                "suggested_heading_count": suggested,
                "avg_heading_count": avg_count,
                "top_headings": top_headings,
                "sources": sources  # 各URLの title と h1/h2/h3 一覧
            })
        except Exception as e:
            return self._json(500, {"error": str(e)})

    def _json(self, status, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
