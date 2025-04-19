#!/usr/bin/env python3
"""
Gringo Fetcher v2

- Downloads the sitemap from URL
- Truncates the XML before parsing
- Writes to local `parsed_sitemap.xml`
- Uses SitemapLoader on the reduced file
- Fetches HTML and stores in gringo.raw_pages
"""

import os, time, logging, requests, psycopg2
from dotenv import load_dotenv
from xml.etree import ElementTree as ET
from langchain_community.document_loaders import SitemapLoader

# ───────────────────────── CONFIG ─────────────────────────
SITEMAP_URL		= "https://gringo.co.il/sitemap.xml"
SITEMAP_TTL		= 7 * 24 * 3600
MAX_PAGES		= 10
HEADERS			= {"User-Agent": "Mozilla/5.0 (GringoFetcher/1.0)"}
PARSED_SITEMAP	= "/app/parsed_sitemap.xml"
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
		except psycopg2.OperationalError:
			if i < retries - 1:
				logging.warning(f"DB not ready, retrying in {delay}s…")
				time.sleep(delay)
			else:
				raise

def download_and_save_truncated_sitemap():
	logging.info(f"Downloading sitemap: {SITEMAP_URL}")
	resp = requests.get(SITEMAP_URL, timeout=15, headers=HEADERS)
	resp.raise_for_status()

	root = ET.fromstring(resp.content)
	ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
	urls = root.findall("sm:url", ns)

	logging.info(f"Original sitemap contains {len(urls)} URLs")

	if MAX_PAGES < len(urls):
		urls = urls[:MAX_PAGES]

	new_root = ET.Element("urlset", {
		"xmlns": "http://www.sitemaps.org/schemas/sitemap/0.9"
	})
	for url in urls:
		new_root.append(url)

	ET.ElementTree(new_root).write(PARSED_SITEMAP, encoding="utf-8", xml_declaration=True)
	logging.info(f"Truncated sitemap saved to {PARSED_SITEMAP} ({len(urls)} URLs)")

def crawl_once():
	download_and_save_truncated_sitemap()

	db = get_db()
	db.autocommit = True
	cur = db.cursor()

	loader = SitemapLoader(web_path=f"file://{PARSED_SITEMAP}")
	docs = loader.load()
	logging.info(f"SitemapLoader returned {len(docs)} docs")

	for doc in docs:
		url = doc.metadata.get("loc") or doc.metadata.get("source") or ""
		if not url:
			continue
		try:
			resp = requests.get(url, timeout=15, headers=HEADERS)
			resp.raise_for_status()
		except Exception as e:
			logging.warning(f"[SKIP] {url} → {e}")
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
		logging.info(f"[OK] Cached {url}")

	cur.close()
	db.close()
	logging.info("Fetch pass complete ✔")

if __name__ == "__main__":
	while True:
		try:
			crawl_once()
			logging.info(f"Sleeping {SITEMAP_TTL // 3600} h…")
			time.sleep(SITEMAP_TTL)
		except Exception as e:
			logging.exception(e)
			time.sleep(300)
