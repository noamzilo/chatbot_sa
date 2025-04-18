#!/usr/bin/env python3
"""
Gringo Fetcher
Step 1 → load sitemap, fetch raw HTML, store in gringo.raw_pages.
Runs forever, sleeping SITEMAP_TTL between passes.
"""

import os, time, logging, requests, psycopg2
from dotenv import load_dotenv
from langchain_community.document_loaders import SitemapLoader

# ───────────────────────── CONFIG ─────────────────────────
SITEMAP_URL		= "https://gringo.co.il/sitemap.xml"
SITEMAP_TTL		= 6 * 3600		# re‑crawl every 6 h
MAX_PAGES		= float("inf")
HEADERS			= {"User-Agent": "Mozilla/5.0 (GringoFetcher/1.0)"}
# ──────────────────────────────────────────────────────────
PROJECT_ROOT	= os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

logging.basicConfig(
	level=logging.INFO,
	format="%(asctime)s [FETCHER] %(levelname)s ▶ %(message)s",
	datefmt="%Y-%m-%d %H:%M:%S",
)

def get_db(retries=5, delay=2):
	for i in range(retries):
		try:
			return psycopg2.connect(
				dbname	=os.getenv("POSTGRES_DB"),
				user	=os.getenv("POSTGRES_USER"),
				password=os.getenv("POSTGRES_PASSWORD"),
				host	=os.getenv("POSTGRES_HOST"),
				port	=os.getenv("POSTGRES_PORT"),
			)
		except psycopg2.OperationalError as e:
			if i < retries - 1:
				logging.warning(f"DB not ready, retrying in {delay}s…")
				time.sleep(delay)
			else:
				raise


def crawl_once():
	db = get_db()
	db.autocommit = True
	cur = db.cursor()

	logging.info("Loading sitemap…")
	urls = SitemapLoader(SITEMAP_URL).load()
	if MAX_PAGES != float("inf"):
		urls = urls[: int(MAX_PAGES)]
	logging.info(f"Found {len(urls)} URLs")

	for doc in urls:
		url = doc.metadata.get("loc") or doc.metadata.get("source") or ""
		if not url:
			continue
		try:
			resp = requests.get(url, timeout=15, headers=HEADERS)
			resp.raise_for_status()
		except Exception as e:
			logging.warning(f"Skip {url} → {e}")
			continue

		cur.execute(
			"""
			insert into gringo.raw_pages(url, html)
			values (%s, %s)
			on conflict(url) do update
			set html = excluded.html,
				fetched_at = current_timestamp
			""",
			(url, resp.text),
		)
		logging.info(f"Cached {url}")

	cur.close()
	db.close()
	logging.info("Pass finished ✔")

if __name__ == "__main__":
	while True:
		try:
			crawl_once()
			logging.info(f"Sleeping {SITEMAP_TTL//3600} h…")
			time.sleep(SITEMAP_TTL)
		except Exception as e:
			logging.exception(e)
			time.sleep(300)		# wait 5 min and retry
