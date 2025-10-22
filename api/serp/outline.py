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

# === Google CSE 検索（軽いリトライ＋例外ハンドリング）===
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
            # 短いジッター付きバックオフ
            time.sleep(0.4 + 0.3 * i + random.random() * 0.2)
    # 失敗時は空配列（上位でメッセージ化）
    return []

# === 見出し抽出（軽いリトライ）===
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
            time.sleep(0.2 + 0.2 * i)  # 短いバックオフ
    return {"url": url, "title": "", "headings": []}

# === メインハンドラ ===
class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            start = time.time()
            parsed = urllib.parse.urlparse(self.path)
            qs = urllib.parse.parse_qs(parsed.query)

            keyword = (qs.get("keyword") or [None])[0]
            # 失敗しやすい時は num を小さめにして負荷軽減
            num = min(int((qs.get("num") or ["8"])[0]), 10)  # 最大10
            lang = (qs.get("lang") or ["ja"])[0]
            country = (qs.get("country") or ["jp"])[0]

            if not keyword:
                return self._json(400, {"error": "missing keyword"})

            urls = cse_search(keyword, num=num, lang=lang, country=country)
            if not urls:
                # 外部API（CSE）側の一時障害・レート制限が濃厚
                return self._json(
                    503,
                    {
                        "error": "upstream_unavailable",
                        "message": "External search API might be throttling or temporarily unavailable. Please retry later.",
                    },
                )

            # 並列取得（総時間ガード）
            sources = []
            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
                futs = {ex.submit(fetch_headings, u): u for u in urls}
                for fut in as_completed(futs):
                    sources.append(fut.result())
                    if time.time() - start > OVERALL_BUDGET:
                        break

            # 集計
            texts = [h["text"] for s in sources for h in s.get("headings", []) if h.get("text")]
            freq = Counter(texts)
            top_headings = [{"text": t, "count": c} for t, c in freq.most_common(30)]

            counts = [len(s.get("headings", [])) for s in sources if s.get("headings")]
            avg_count = round(sum(counts) / len(counts), 1) if counts else 0
            suggested = int(round(avg_count)) if avg_count else 10
            suggested = max(6, min(20, suggested))

            partial = len(sources) < len(urls)

            return self._json(
                200,
                {
                    "keyword": keyword,
                    "sampled": len(sources),
                    "suggested_heading_count": suggested,
                    "avg_heading_count": avg_count,
                    "top_headings": top_headings,
                    "sources": sources,
                    "partial": partial,
                    "elapsed": round(time.time() - start, 2),
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
