# api/serp/outline.py
from http.server import BaseHTTPRequestHandler
import os, json, urllib.parse, time, re, unicodedata, random
import requests
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter

# === 環境変数 ===
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
GOOGLE_CSE_ID = os.getenv("GOOGLE_CSE_ID")

# === 並列処理とタイムアウト設定 ===
MAX_WORKERS = 6          # 同時取得数
PER_REQ_TIMEOUT = 6      # 各URL取得のタイムアウト秒
OVERALL_BUDGET = 8.0     # 全体の猶予時間（秒）

# === requests セッション（自動リトライ付き）===
_session = requests.Session()
_retries = Retry(
    total=3,
    backoff_factor=0.5,                         # 0.5, 1.0, 2.0...
    status_forcelist=[429, 500, 502, 503, 504],
    allowed_methods=["GET"],
    raise_on_status=False,
)
_adapter = HTTPAdapter(max_retries=_retries, pool_connections=20, pool_maxsize=20)
_session.mount("http://", _adapter)
_session.mount("https://", _adapter)

COMMON_HEADERS = {
    "User-Agent": "Mozilla/5.0 (SERP-Outline-Bot)",
    "Accept-Language": "ja-JP,ja;q=0.9,en;q=0.8",
}

# === Google CSE 検索 ===
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
        "safe": "off",
    }
    tries = 2
    for i in range(tries):
        try:
            r = _session.get(url, params=params, timeout=6)
            r.raise_for_status()
            items = r.json().get("items", []) or []
            return [it.get("link") for it in items if it.get("link")]
        except Exception:
            time.sleep(0.4 + 0.3 * i + random.random() * 0.2)
    return []

# === 見出し抽出 ===
def fetch_headings(url, timeout=PER_REQ_TIMEOUT):
    for i in range(2):  # 2回だけ試す
        try:
            r = _session.get(url, timeout=timeout, headers=COMMON_HEADERS)
            r.raise_for_status()
            soup = BeautifulSoup(r.content, "lxml")

            # タイトル（og:title フォールバック）
            title = ""
            if soup.title and soup.title.string:
                title = soup.title.string.strip()
            else:
                og = soup.find("meta", property="og:title")
                if og and og.get("content"):
                    title = og.get("content").strip()

            # 見出しのクレンジング
            def clean(txt: str) -> str:
                txt = re.sub(r"\s+", " ", txt).strip()
                txt = unicodedata.normalize("NFKC", txt)
                txt = re.sub(r"^\d+[\.\)\-、]+\s*", "", txt)  # 先頭の番号/記号除去
                return txt

            hs = []
            for tag in soup.select("h1, h2, h3"):
                txt = clean(tag.get_text(" ", strip=True))
                if txt:
                    hs.append({"tag": tag.name.lower(), "text": txt})

            return {"url": url, "title": title, "headings": hs}
        except Exception:
            time.sleep(0.2 + 0.2 * i)
    return {"url": url, "title": "", "headings": []}

# === メインハンドラ ===
class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            start = time.time()
            parsed = urllib.parse.urlparse(self.path)
            qs = urllib.parse.parse_qs(parsed.query)

            keyword = (qs.get("keyword") or [None])[0]
            mode = (qs.get("mode") or ["full"])[0]  # "full" | "lite"
            # 最大10。liteは初期値5で軽く。
            default_num = "5" if mode == "lite" else "8"
            num = min(int((qs.get("num") or [default_num])[0]), 10)
            lang = (qs.get("lang") or ["ja"])[0]
            country = (qs.get("country") or ["jp"])[0]

            # 手動URL指定: ?urls=https://a.com,https://b.com
            raw_urls = (qs.get("urls") or [None])[0]
            manual_urls = []
            if raw_urls:
                manual_urls = [u.strip() for u in raw_urls.split(",") if u.strip()]

            if not keyword and not manual_urls:
                return self._json(400, {"error": "missing keyword or urls"})

            # URLの決定
            if manual_urls:
                urls = manual_urls[:num]
                url_source = "manual"
            else:
                urls = cse_search(keyword, num=num, lang=lang, country=country)
                url_source = "cse"

            if not urls:
                status = "unavailable" if url_source == "cse" else "ok"
                return self._json(
                    503 if url_source == "cse" else 200,
                    {
                        "status": status,
                        "keyword": keyword or "",
                        "sampled": 0,
                        "suggested_heading_count": 12,           # フォールバック既定
                        "avg_heading_count": 0,
                        "top_headings": [],
                        "sources": [],
                        "partial": False,
                        "elapsed": round(time.time() - start, 2),
                        "message": "External search API unavailable. Using fallback defaults."
                                   if url_source == "cse" else "No URLs provided.",
                        "url_source": url_source,
                        "mode": mode,
                    },
                )

            # === LITE モード：HTML取得なしで titles のみ（見出しは空）
            if mode == "lite":
                sources = [{"url": u, "title": "", "headings": []} for u in urls]
                suggested = 12  # 安全な既定値
                return self._json(
                    200,
                    {
                        "status": "degraded",
                        "keyword": keyword or "",
                        "sampled": len(sources),
                        "suggested_heading_count": suggested,
                        "avg_heading_count": 0,
                        "top_headings": [],
                        "sources": sources,
                        "partial": False,
                        "elapsed": round(time.time() - start, 2),
                        "message": "Lite mode (no HTML fetch).",
                        "url_source": url_source,
                        "mode": mode,
                    },
                )

            # === FULL モード：並列取得（総時間ガード）
            sources = []
            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
                futs = {ex.submit(fetch_headings, u): u for u in urls}
                for fut in as_completed(futs):
                    sources.append(fut.result())
                    if time.time() - start > OVERALL_BUDGET:
                        break

            texts = [h["text"] for s in sources for h in s.get("headings", []) if h.get("text")]
            freq = Counter(texts)
            top_headings = [{"text": t, "count": c} for t, c in freq.most_common(30)]
            counts = [len(s.get("headings", [])) for s in sources if s.get("headings")]
            avg_count = round(sum(counts) / len(counts), 1) if counts else 0
            suggested = int(round(avg_count)) if avg_count else 12
            suggested = max(6, min(20, suggested))
            partial = len(sources) < len(urls)

            return self._json(
                200,
                {
                    "status": "partial" if partial else "ok",
                    "keyword": keyword or "",
                    "sampled": len(sources),
                    "suggested_heading_count": suggested,
                    "avg_heading_count": avg_count,
                    "top_headings": top_headings,
                    "sources": sources,
                    "partial": partial,
                    "elapsed": round(time.time() - start, 2),
                    "url_source": url_source,
                    "mode": mode,
                },
            )
        except Exception as e:
            return self._json(500, {"error": str(e)})

    def _json(self, status, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
