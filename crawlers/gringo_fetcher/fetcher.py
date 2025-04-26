#!/usr/bin/env python3
"""
Gringo Fetcher – step 1
Download first N URLs from Gringo sitemap and publish rows to gringo.raw_pages.
Publishes “gringo:fetcher:done” on Redis when finished.
"""

import os, time, logging, requests, psycopg2, redis, json, warnings
from dotenv           import load_dotenv
from xml.etree         import ElementTree as ET
from bs4               import BeautifulSoup            # only for safe_parsing
from pathlib           import Path

# ───────────────────────── CONFIG ─────────────────────────
SITEMAP_URL  = "https://gringo.co.il/sitemap.xml"
SITEMAP_TTL  = 7 * 24 * 3600
MAX_PAGES    = 10

UA = os.getenv("USER_AGENT") or \
     "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
HEADERS = {"User-Agent": UA}
# ──────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

logging.basicConfig(
    level   = logging.DEBUG,
    format  = "%(asctime)s [FETCHER] %(levelname)s ▶ %(message)s",
    datefmt = "%Y-%m-%d %H:%M:%S",
)

# ───────────────────────── helpers ────────────────────────
def get_redis():
    return redis.Redis(
        host = os.getenv("REDIS_HOST", "localhost"),
        port = int(os.getenv("REDIS_PORT", 6379)),
        db   = 0,
        decode_responses = True,
    )

def get_db(retries: int = 10, delay: int = 2):
    for i in range(retries):
        try:
            return psycopg2.connect(
                dbname   = os.getenv("POSTGRES_DB"),
                user     = os.getenv("POSTGRES_USER"),
                password = os.getenv("POSTGRES_PASSWORD"),
                host     = os.getenv("POSTGRES_HOST"),
                port     = os.getenv("POSTGRES_PORT"),
            )
        except psycopg2.OperationalError as e:
            logging.warning(f"DB not ready, retrying in {delay}s… ({e})")
            if i < retries - 1:
                time.sleep(delay)
            else:
                raise

def download_sitemap() -> bytes:
    """Try live sitemap first, fallback to baked file inside image."""
    try:
        resp = requests.get(SITEMAP_URL, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        return resp.content
    except Exception as e:
        cached = os.getenv("SITEMAP_CACHED", "")
        if cached and Path(cached).exists():
            warnings.warn(f"Remote sitemap failed ({e}); using cached copy")
            return Path(cached).read_bytes()
        raise

def get_first_n_urls(n: int) -> list[str]:
    logging.info(f"Downloading sitemap: {SITEMAP_URL}")
    raw_xml = download_sitemap()
    root = ET.fromstring(raw_xml)
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    locs = [
        loc.text.strip()
        for loc in (tag.find("sm:loc", ns) for tag in root.findall("sm:url", ns))
        if loc is not None and loc.text
    ]
    logging.info(f"Loaded {len(locs)} URLs from sitemap")
    return locs[:n]

# ↓ unchanged helper
def safe_parsing(bs: BeautifulSoup) -> str:
    if bs is None:
        return ""
    try:
        h1      = bs.find('h1')
        title   = " ".join(h1.stripped_strings) if h1 else ""
        section = bs.find('section', class_='text-body')
        content = " ".join(section.stripped_strings) if section else ""
        return json.dumps({"title": title, "content": content}, ensure_ascii=False)
    except Exception as e:
        logging.warning(f"[PARSE FAIL] {e}")
        return ""

# ───────────────────────── main crawl ─────────────────────
def crawl_once():
    logging.info(f"Loading first {MAX_PAGES} pages via custom list…")
    urls = get_first_n_urls(MAX_PAGES)

    db  = get_db(); db.autocommit = True
    cur = db.cursor()

    for url in urls:
        try:
            html = safe_parsing(BeautifulSoup(requests.get(url, headers=HEADERS, timeout=15).text, "html.parser"))
        except Exception as e:
            logging.error(f"[FETCH FAIL] {url} → {e}")
            continue

        if not html.strip():
            logging.warning(f"[SKIP] {url} → empty content")
            continue

        preview = html[:100].replace("\n", " ")
        logging.info(f"[INSERT] {url} ({len(html)} chars)")
        logging.debug(f"[CONTENT PREVIEW] {preview}…")
        try:
            cur.execute(
                """
                INSERT INTO gringo.raw_pages(url, relevant_content)
                VALUES (%s,%s)
                ON CONFLICT(url) DO UPDATE
                SET relevant_content = excluded.relevant_content,
                    fetched_at      = current_timestamp
                """,
                (url, html),
            )
        except Exception as e:
            logging.error(f"[DB FAIL] {url} → {e}")

    cur.close(); db.close()
    logging.info("Fetch pass complete ✔")

# ───────────────────────── entrypoint loop ────────────────
if __name__ == "__main__":
    while True:
        try:
            crawl_once()
            get_redis().publish('gringo:fetcher:done', '1')
            logging.info("Sent completion signal to parser")
            time.sleep(SITEMAP_TTL)
        except Exception as e:
            logging.error(f"Error in fetcher main loop: {e}")
            time.sleep(60)
