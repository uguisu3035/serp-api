#!/usr/bin/env python3
"""
serp_charcount.py
---------------------------------
Get the average character count of the top 10 Google results for a given keyword.
Uses Google Custom Search JSON API + Readability.
Outputs a table and saves a CSV.

Setup:
1) pip install -r requirements.txt
2) Set environment variables:
   - GOOGLE_API_KEY
   - GOOGLE_CSE_ID (a Programmable Search Engine set to search the entire web)
   (You can put them in a .env file in the same folder.)

Usage:
   python serp_charcount.py "キーワード"
   # Optional flags:
   --num 10               # how many results to measure (default 10, max 10 per API page)
   --lang ja              # lang parameter passed to CSE (default ja)
   --country jp           # gl parameter passed to CSE (default jp)
   --csv out.csv          # output CSV filename (default results.csv)
"""

import os
import sys
import time
import csv
import argparse
import re
from urllib.parse import quote_plus
import requests

try:
    from bs4 import BeautifulSoup
    from readability import Document
except ImportError:
    print("Missing dependencies. Run: pip install -r requirements.txt")
    sys.exit(1)

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    # dotenv is optional; skip if not installed
    pass

API_KEY = os.getenv("GOOGLE_API_KEY", "").strip()
CSE_ID  = os.getenv("GOOGLE_CSE_ID", "").strip()

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/124.0.0.0 Safari/537.36"
}

def clean_text(text: str) -> str:
    # Remove excessive whitespace and boilerplate artifacts
    text = re.sub(r'\s+', '', text)  # collapse and remove whitespace for character count
    return text

def extract_main_text(html: str, url: str) -> str:
    # First try Readability (best-effort "article" extraction)
    try:
        doc = Document(html)
        summary_html = doc.summary()
        soup = BeautifulSoup(summary_html, "lxml")
        text = soup.get_text(separator=" ")
        text = clean_text(text)
        if len(text) >= 200:  # basic sanity
            return text
    except Exception:
        pass

    # Fallback: plain text from full HTML (can be noisy)
    try:
        soup = BeautifulSoup(html, "lxml")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        text = soup.get_text(separator=" ")
        return clean_text(text)
    except Exception:
        return ""

def fetch(url: str, timeout: int = 15) -> str:
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        if r.status_code == 200 and "text/html" in r.headers.get("Content-Type",""):
            return r.text
    except Exception:
        return ""
    return ""

def cse_search(query: str, num: int = 10, lang: str = "ja", country: str = "jp"):
    if not API_KEY or not CSE_ID:
        print("ERROR: GOOGLE_API_KEY and/or GOOGLE_CSE_ID are not set.")
        sys.exit(2)

    # Google CSE returns up to 10 results per request
    params = {
        "key": API_KEY,
        "cx": CSE_ID,
        "q": query,
        "num": min(10, num),
        "hl": lang,
        "lr": f"lang_{lang}" if lang else None,
        "gl": country,
        "safe": "off",
    }
    # Remove None values
    params = {k:v for k,v in params.items() if v is not None}

    resp = requests.get("https://www.googleapis.com/customsearch/v1", params=params, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    items = data.get("items", []) or []
    # Prefer "link" field; skip non-http(s)
    urls = [it.get("link") for it in items if it.get("link","").startswith(("http://","https://"))]
    # Limit to requested num
    return urls[:num]

def main():
    parser = argparse.ArgumentParser(description="Average character count of top SERP pages for a keyword")
    parser.add_argument("keyword", type=str, help="検索キーワード（例：'プログラミング 独学'）")
    parser.add_argument("--num", type=int, default=10, help="取得件数 (default 10, max 10 per API page)")
    parser.add_argument("--lang", type=str, default="ja", help="言語 (default ja)")
    parser.add_argument("--country", type=str, default="jp", help="国 (default jp)")
    parser.add_argument("--csv", type=str, default="results.csv", help="CSV出力先ファイル名")

    args = parser.parse_args()

    print(f"🔎 Keyword: {args.keyword}")
    urls = cse_search(args.keyword, num=args.num, lang=args.lang, country=args.country)

    if not urls:
        print("No results. Try a different keyword or check your API settings.")
        sys.exit(0)

    rows = []
    for rank, url in enumerate(urls, start=1):
        print(f"[{rank}] Fetching: {url}")
        html = fetch(url)
        if not html:
            print("   -> Failed or non-HTML content; skipping.")
            rows.append([rank, url, 0])
            continue

        text = extract_main_text(html, url)
        char_count = len(text)
        print(f"   -> Characters: {char_count}")
        rows.append([rank, url, char_count])
        time.sleep(1)  # be polite

    # Compute average (ignore zeros? We'll include them but you can filter later)
    counts = [r[2] for r in rows if r[2] > 0]
    avg = sum(counts) / len(counts) if counts else 0

    # Pretty print
    print("\n=== Results ===")
    for r in rows:
        print(f"{r[0]:>2}. {r[2]:>8}  {r[1]}")
    print(f"\nAverage (non-zero): {int(avg)} chars over {len(counts)} pages")

    # Save CSV
    out = args.csv
    with open(out, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["rank", "url", "char_count"])
        writer.writerows(rows)
        writer.writerow([])
        writer.writerow(["average_non_zero", int(avg)])
    print(f"\nSaved CSV -> {out}")

if __name__ == "__main__":
    main()
