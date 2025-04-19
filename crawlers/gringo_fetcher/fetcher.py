#!/usr/bin/env python3
"""
Gringo Fetcher

- Downloads sitemap
- Extracts first N URLs
- Uses SitemapLoader with filter_urls
- Fetches HTML and stores in gringo.raw_pages
"""

import os
import time
import logging
import requests
import psycopg2
import re
from dotenv import load_dotenv
from xml.etree import ElementTree as ET
from langchain_community.document_loaders import SitemapLoader

# ───────────────────────── CONFIG ─────────────────────────
SITEMAP_URL = "https://gringo.co.il/sitemap.xml"
SITEMAP_TTL = 7 * 24 * 3600
MAX_PAGES = 10
HEADERS = {"User-Agent": "Mozilla/5.0 (GringoFetcher/1.0)"}
# ──────────────────────────────────────────────────────────
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

logging.basicConfig(
	level=logging.INFO,
	format="%(asctime)s [FETCHER] %(levelname)s ▶ %(message)s",
	datefmt="%Y-%m-%d %H:%M:%S",
)

def get_db(retries=10, delay=2):
	for i in range(retries):
		try:
			conn = psycopg2.connect(
				dbname=os.getenv("POSTGRES_DB"),
				user=os.getenv("POSTGRES_USER"),
				password=os.getenv("POSTGRES_PASSWORD"),
				host=os.getenv("POSTGRES_HOST"),
				port=os.getenv("POSTGRES_PORT"),
			)
			return conn
		except psycopg2.OperationalError as e:
			if "does not exist" in str(e):
				logging.warning(f"Database doesn't exist yet, retrying in {delay}s…")
			else:
				logging.warning(f"DB not ready, retrying in {delay}s…")
			if i < retries - 1:
				time.sleep(delay)
			else:
				raise

def get_first_n_urls_from_sitemap(url: str, n: int) -> list[str]:
	logging.info(f"Downloading sitemap: {url}")
	resp = requests.get(url, timeout=15, headers=HEADERS)
	resp.raise_for_status()
	root = ET.fromstring(resp.content)
	ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
	url_tags = root.findall("sm:url", ns)
	locs = []
	for tag in url_tags:
		loc = tag.find("sm:loc", ns)
		if loc is not None and loc.text:
			locs.append(loc.text.strip())
		if len(locs) >= n:
			break
	logging.info(f"Loaded {len(locs)} URLs from sitemap")
	return locs

def crawl_once():
	subset = get_first_n_urls_from_sitemap(SITEMAP_URL, MAX_PAGES)
	# Escape dots in URLs to match literal dots in regex
	escaped_urls = [re.escape(url) for url in subset]
	loader = SitemapLoader(
		web_path=SITEMAP_URL,
		filter_urls=escaped_urls,
		restrict_to_same_domain=False
	)
	docs = loader.load()
	logging.info(f"SitemapLoader returned {len(docs)} docs")

	db = get_db()
	db.autocommit = True
	cur = db.cursor()

	for doc in docs:
		url = doc.metadata.get("source") or doc.metadata.get("loc") or ""
		if not url:
			continue
		html = doc.page_content
		if not html.strip():
			logging.warning(f"[SKIP] {url} → empty content")
			continue
		try:
			cur.execute(
				"""
				INSERT INTO gringo.raw_pages(url, html)
				VALUES (%s, %s)
				ON CONFLICT(url) DO UPDATE
				SET html = excluded.html,
					fetched_at = current_timestamp
				""",
				(url, html),
			)
			logging.info(f"[OK] Cached {url}")
		except Exception as e:
			logging.error(f"[FAIL] DB error for {url} → {e}")

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
