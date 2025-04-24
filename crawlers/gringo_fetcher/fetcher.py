#!/usr/bin/env python3
import os
import time
import logging
import requests
import psycopg2
from dotenv import load_dotenv
from xml.etree import ElementTree as ET
from langchain_community.document_loaders import SitemapLoader
from bs4 import BeautifulSoup
import json

# ───────────────────────── CONFIG ─────────────────────────
SITEMAP_URL = "https://gringo.co.il/sitemap.xml"
SITEMAP_TTL = 7 * 24 * 3600
MAX_PAGES = 10
HEADERS = {"User-Agent": "Mozilla/5.0 (GringoFetcher/1.0)"}
# ──────────────────────────────────────────────────────────
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

logging.basicConfig(
	level=logging.DEBUG,
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
			logging.warning(f"DB not ready, retrying in {delay}s… ({e})")
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

def safe_parsing(bs):
	if bs is None:
		return ""
	try:
		# Extract h1 title
		h1 = bs.find('h1')
		title = " ".join(h1.stripped_strings) if h1 else ""
		
		# Extract main content from section.text-body
		content_section = bs.find('section', class_='text-body')
		content = " ".join(content_section.stripped_strings) if content_section else ""
		
		# Create JSON structure
		result = json.dumps({
			"title": title,
			"content": content
		}, ensure_ascii=False)
		
		return result
	except Exception as e:
		logging.warning(f"[PARSE FAIL] Could not extract text: {e}")
		return ""

def crawl_once():
	logging.info(f"Loading first {MAX_PAGES} pages via blocksize…")
	loader = SitemapLoader(
		web_path=SITEMAP_URL,
		blocksize=MAX_PAGES,
		blocknum=0,
		restrict_to_same_domain=False,
		parsing_function=safe_parsing
	)

	docs = loader.load()
	logging.info(f"SitemapLoader returned {len(docs)} docs")

	db = get_db()
	db.autocommit = True
	cur = db.cursor()

	for i, doc in enumerate(docs):
		url = doc.metadata.get("source") or doc.metadata.get("loc") or ""
		html = doc.page_content

		if not url:
			logging.warning("[SKIP] No URL in doc")
			continue

		if not html.strip():
			logging.warning(f"[SKIP] {url} → empty content")
			continue

		# Log a preview of the processed content
		preview = html[:100].replace('\n', ' ').strip()
		logging.info(f"[INSERT] {url} → {len(html)} chars")
		logging.debug(f"[CONTENT PREVIEW] {url} → {preview}...")

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
		except Exception as e:
			logging.error(f"[FAIL] DB error for {url} → {e}")
			logging.error(f"Content type: {type(html)}, Length: {len(html)}")

	cur.close()
	db.close()
	logging.info("Fetch pass complete ✔")

if __name__ == "__main__":
	crawl_once()
