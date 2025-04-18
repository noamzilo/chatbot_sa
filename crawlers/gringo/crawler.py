#!/usr/bin/env python3
"""
Gringo crawler v3
• Uses LangChain's SitemapLoader (no DIY parsing)
• Caches sitemap URLs + raw HTML in Postgres
• Stores one row per page in gringo.documents with pgvector
"""

import os, time, requests, psycopg2
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
from pgvector.psycopg2 import register_vector
from langchain_community.document_loaders import SitemapLoader
from langchain_openai import OpenAIEmbeddings

# ───────────────────────── CONFIG ─────────────────────────
SITEMAP_URL	= "https://gringo.co.il/sitemap.xml"
SITEMAP_TTL	= 7 * 24 * 3600	# 7 days
MAX_PAGES	= 1				# `set to float("inf") in prod
# ──────────────────────────────────────────────────────────
PROJECT_ROOT	= os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

class GringoCrawler:
	def __init__(self):
		print("[INIT] Connecting to DB…")
		self.db = psycopg2.connect(
			dbname	=os.getenv("POSTGRES_DB"),
			user	=os.getenv("POSTGRES_USER"),
			password=os.getenv("POSTGRES_PASSWORD"),
			host	=os.getenv("POSTGRES_HOST"),
			port	=os.getenv("POSTGRES_PORT")
		)
		register_vector(self.db)
		self.db.autocommit = False		# manual commits

		print("[INIT] Loading OpenAI embeddings…")
		self.embedder = OpenAIEmbeddings(openai_api_key=os.getenv("OPENAI_API_KEY"))
		print("[INIT] Ready ✅")

	# ──────── Sitemap caching ────────
	def _load_sitemap_urls(self):
		with self.db.cursor() as cur:
			cur.execute("select count(*), max(fetched_at) from gringo.sitemap_cache")
			n_rows, last_ts = cur.fetchone()
			if n_rows and last_ts and (time.time() - last_ts.timestamp() < SITEMAP_TTL):
				cur.execute("select url from gringo.sitemap_cache order by url")
				return [r[0] for r in cur.fetchall()]

		# cache miss → refresh
		print("[CACHE] Refreshing sitemap cache…")
		now = datetime.now(timezone.utc)
		headers = {"User-Agent": "Mozilla/5.0 (compatible; GringoCrawler/1.0)"}
		resp   = requests.get(SITEMAP_URL, timeout=10, headers=headers)
		resp.raise_for_status()

		loader = SitemapLoader(SITEMAP_URL)
		urls   = loader._get_loc_entries(resp.text)	# returns list[str]
		with self.db.cursor() as cur:
			cur.executemany(
				"insert into gringo.sitemap_cache(url, fetched_at) values (%s, %s) "
				"on conflict(url) do update set fetched_at = excluded.fetched_at",
				[(u, now) for u in urls]
			)
			self.db.commit()
		return urls

	# ──────── Raw HTML cache ────────
	def _get_raw_html(self, url):
		with self.db.cursor() as cur:
			cur.execute("select id, html from gringo.raw_pages where url=%s", (url,))
			row = cur.fetchone()
			if row:
				return row[0], row[1]

		headers = {"User-Agent": "Mozilla/5.0 (compatible; GringoCrawler/1.0)"}
		resp = requests.get(url, timeout=10, headers=headers)
		resp.raise_for_status()
		html = resp.text

		with self.db.cursor() as cur:
			cur.execute(
				"insert into gringo.raw_pages(url,html) values(%s,%s) "
				"on conflict(url) do update set html=excluded.html "
				"returning id",
				(url, html)
			)
			raw_id = cur.fetchone()[0]
			self.db.commit()
		return raw_id, html

	# ───────────────────────────── Crawl ────────────────────────────
	def crawl(self):
		print("[CRAWLER] Loading sitemap…")
		all_urls = self._load_sitemap_urls()
		if MAX_PAGES != float("inf"):
			all_urls = all_urls[:int(MAX_PAGES)]
		print(f"[CRAWLER] Crawling {len(all_urls)} URL(s)…")

		loader = SitemapLoader(SITEMAP_URL, is_local=False, filter_urls=all_urls)
		pages  = loader.load()

		for doc in pages:
			url		= doc.metadata.get("loc") or doc.metadata.get("source") or ""
			content	= doc.page_content.strip()
			if not url or not content:
				continue

			raw_id, _html = self._get_raw_html(url)
			embedding = self.embedder.embed_query(content)

			with self.db.cursor() as cur:
				cur.execute("""
					insert into gringo.documents(url,title,content,embedding,raw_page_id)
					values (%s,%s,%s,%s,%s)
					on conflict(url) do update
					set	title     = excluded.title,
						content   = excluded.content,
						embedding = excluded.embedding,
						raw_page_id=excluded.raw_page_id,
						updated_at=current_timestamp
				""", (url, doc.metadata.get("title",""), content, embedding, raw_id))
				self.db.commit()

		print("[DONE] Crawler cycle finished.\n")

# ─────────────────────────── Runner ──────────────────────────────
if __name__ == "__main__":
	while True:
		try:
			GringoCrawler().crawl()
			print("[SLEEP] 1 h…")
			time.sleep(3600)
		except Exception as e:
			print(f"[ERROR] {e} – retry in 5 min")
			time.sleep(300)
