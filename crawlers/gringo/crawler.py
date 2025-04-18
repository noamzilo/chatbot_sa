#!/usr/bin/env python3
"""
Gringo crawler v4
• Step 1: Use LangChain's SitemapLoader to get URLs
• Step 2: Fetch raw HTML with headers → store in gringo.raw_pages
• Step 3: Parse & embed from gringo.raw_pages → store in gringo.documents
"""

import os, time, requests, psycopg2
from datetime import datetime, timezone
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from pgvector.psycopg2 import register_vector
from langchain_community.document_loaders import SitemapLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings
from tqdm import tqdm

# ───────────────────────── CONFIG ─────────────────────────
SITEMAP_URL		= "https://gringo.co.il/sitemap.xml"
SITEMAP_TTL		= 7 * 24 * 3600
CHUNK_SIZE		= 1000
CHUNK_OVERLAP	= 200
MAX_PAGES		= float("inf")
HEADERS = {
	"User-Agent": "Mozilla/5.0 (compatible; GringoCrawler/1.0)"
}
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
		self.db.set_session(autocommit=True)
		register_vector(self.db)
		self.db.set_session(autocommit=False)

		print("[INIT] Loading OpenAI embeddings…")
		self.embedder = OpenAIEmbeddings(openai_api_key=os.getenv("OPENAI_API_KEY"))
		print("[INIT] Ready ✅")

	def crawl_to_db(self):
		print("[CRAWLER] Loading sitemap…")
		loader = SitemapLoader(SITEMAP_URL)
		all_docs = loader.load()

		if MAX_PAGES != float("inf"):
			all_docs = all_docs[:int(MAX_PAGES)]
		print(f"[CRAWLER] Got {len(all_docs)} URLs.")

		for doc in all_docs:
			url = doc.metadata.get("loc") or doc.metadata.get("source") or ""
			if not url: continue

			try:
				resp = requests.get(url, timeout=10, headers=HEADERS)
				resp.raise_for_status()
				html = resp.text
			except Exception as e:
				print(f"[SKIP] {url} → {e}")
				continue

			with self.db.cursor() as cur:
				cur.execute("""
					insert into gringo.raw_pages(url, html)
					values (%s, %s)
					on conflict(url) do update
					set html = excluded.html,
						fetched_at = current_timestamp
				""", (url, html))
				self.db.commit()
				print(f"[OK] Saved raw HTML for: {url}")

		print("[DONE] Crawl completed and stored in gringo.raw_pages.\n")

	def parse_and_embed(self):
		print("[EMBED] Fetching uncached pages from gringo.raw_pages…")
		with self.db.cursor() as cur:
			cur.execute("""
				select rp.id, rp.url, rp.html
				from gringo.raw_pages rp
				left join gringo.documents d on rp.id = d.raw_page_id
				where d.id is null
			""")
			rows = cur.fetchall()

		print(f"[EMBED] Found {len(rows)} unprocessed raw pages.")
		splitter = RecursiveCharacterTextSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)

		for raw_id, url, html in tqdm(rows, desc="Embedding"):
			soup = BeautifulSoup(html, "lxml")
			title = soup.title.string if soup.title else ""
			content = soup.get_text("\n", strip=True)

			if not content:
				print(f"[SKIP] {url} — empty content.")
				continue

			chunks = splitter.split_text(content)
			if not chunks:
				print(f"[SKIP] {url} — no chunks.")
				continue

			full_content = "\n\n".join(chunks)
			embedding = self.embedder.embed_query(full_content)

			with self.db.cursor() as cur:
				cur.execute("""
					insert into gringo.documents(url, title, content, embedding, raw_page_id)
					values (%s, %s, %s, %s, %s)
					on conflict(url) do update
					set title = excluded.title,
						content = excluded.content,
						embedding = excluded.embedding,
						raw_page_id = excluded.raw_page_id,
						updated_at = current_timestamp
				""", (url, title, full_content, embedding, raw_id))
				self.db.commit()

		print("[DONE] Embedding completed.\n")

# ──────────────────────────── Runner ──────────────────────────────
if __name__ == "__main__":
	while True:
		try:
			crawler = GringoCrawler()
			crawler.crawl_to_db()
			crawler.parse_and_embed()
			print("[SLEEP] 1 h…")
			time.sleep(3600)
		except Exception as e:
			print(f"[ERROR] {e} – retry in 5 min")
			time.sleep(300)
