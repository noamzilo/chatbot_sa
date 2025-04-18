#!/usr/bin/env python3
"""
Gringo site crawler:
• Fetches sitemap• Caches raw HTML in Postgres (TTL‑7 days)• Embeds & stores chunks
"""

import os, time, json, requests, psycopg2
from typing import List
from bs4 import BeautifulSoup
from xml.etree import ElementTree as ET
from dotenv import load_dotenv
from psycopg2.extras import execute_values
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings
from langchain.docstore.document import Document
from tqdm import tqdm

# ──────────────────────────── CONFIG ────────────────────────────
SITEMAP_URL	= "https://gringo.co.il/sitemap.xml"
CACHE_TTL_S	= 7 * 24 * 3600				# 1 week
CHUNK_SIZE	= 1000
CHUNK_OVERLAP	= 200
MAX_PAGES	= 10 #float("inf")				# ← override for debug (e.g., 100)
# ────────────────────────────────────────────────────────────────
PROJECT_ROOT	= os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

class GringoCrawler:
	def __init__(self):
		print("[INIT] Connecting to DB…")
		self.db = psycopg2.connect(
			dbname	= os.getenv("POSTGRES_DB"),
			user	= os.getenv("POSTGRES_USER"),
			password= os.getenv("POSTGRES_PASSWORD"),
			host	= os.getenv("POSTGRES_HOST"),
			port	= os.getenv("POSTGRES_PORT")
		)
		print("[INIT] DB OK.")
		print("[INIT] Loading OpenAI embeddings…")
		self.embedder = OpenAIEmbeddings(openai_api_key=os.getenv("OPENAI_API_KEY"))
		print("[INIT] Embeddings ready.")

	# ────────────────  Raw‑HTML cache helpers  ────────────────
	def _get_or_insert_raw_html(self, url: str) -> tuple[int, str]:
		with self.db.cursor() as cur:
			cur.execute("select id, html, fetched_at from gringo.raw_pages where url=%s", (url,))
			row = cur.fetchone()
			if row:
				id, html, fetched_at = row
				if time.time() - fetched_at.timestamp() < CACHE_TTL_S:
					return id, html

			resp = requests.get(url, timeout=10)
			resp.raise_for_status()
			html = resp.text
			cur.execute("""
				insert into gringo.raw_pages(url, html, fetched_at)
				values(%s,%s,current_timestamp)
				on conflict(url) do update
				set html = excluded.html,
				    fetched_at = current_timestamp
				returning id
			""", (url, html))
			return cur.fetchone()[0], html

	def _get_or_create_affiliate(self, url: str, text: str) -> int:
		with self.db.cursor() as cur:
			cur.execute("""
				insert into gringo.affiliate_links(url, link_text)
				values(%s,%s)
				on conflict(url, link_text) do update
				set updated_at = current_timestamp
				returning id
			""", (url, text))
			return cur.fetchone()[0]

	def _store_page(self, url: str, title: str, content: str, embedding: List[float], raw_id: int) -> int:
		with self.db.cursor() as cur:
			cur.execute("""
				insert into gringo.pages(url,title,content,embedding,raw_page_id)
				values(%s,%s,%s,%s,%s)
				on conflict(url) do update
				set title       = excluded.title,
				    content     = excluded.content,
				    embedding   = excluded.embedding,
				    raw_page_id = excluded.raw_page_id,
				    updated_at  = current_timestamp
				returning id
			""", (url, title, content, embedding, raw_id))
			return cur.fetchone()[0]

	def _link_page_affiliates(self, page_id: int, affiliate_ids: List[int]):
		if not affiliate_ids: return
		with self.db.cursor() as cur:
			execute_values(cur, """
				insert into gringo.page_affiliate_links(page_id,affiliate_id)
				values %s
				on conflict do nothing
			""", [(page_id, aid) for aid in affiliate_ids])

	# ───────────────────────────── Crawl ────────────────────────────
	def crawl(self):
		print("Starting crawler…")
		docs = self._load_sitemap_documents()

		# Limit for debugging
		if MAX_PAGES != float("inf"):
			docs = docs[:MAX_PAGES]
			print(f"[DEBUG] Limiting to first {MAX_PAGES} pages.")

		# Split to chunks
		splitter	= RecursiveCharacterTextSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)
		chunks		= splitter.split_documents(docs)
		print(f"[INFO] {len(chunks)} chunks to embed/store.")

		for chunk in tqdm(chunks, desc="Embed & Store"):
			url	= chunk.metadata.get("source","")
			title	= chunk.metadata.get("title","")

			raw_id, html	= self._get_or_insert_raw_html(url)
			soup		= BeautifulSoup(html, "lxml")
			content		= soup.get_text("\n", strip=True)
			if not content:			# skip empty pages
				continue

			embedding	= self.embedder.embed_query(content)
			page_id		= self._store_page(url, title, content, embedding, raw_id)

			affiliate_ids = [
				self._get_or_create_affiliate(a.get("href",""), a.get_text(strip=True))
				for a in soup.find_all("a", href=True)
				if any(k in a["href"].lower() for k in ("affiliate","partner"))
			]
			self._link_page_affiliates(page_id, affiliate_ids)
			self.db.commit()

		print("Crawler finished successfully.")

	# ────────────────────── Sitemap fetch helpers ─────────────────────
	def _load_sitemap_documents(self) -> List[Document]:
		try:
			from langchain_community.document_loaders import SitemapLoader
			loader		= SitemapLoader(SITEMAP_URL)
			documents	= loader.load()
			print(f"[INFO] LangChain loader fetched {len(documents)} URLs.")
			return documents
		except Exception as e:
			print(f"[WARN] SitemapLoader failed ({e}) – falling back to raw XML.")
			resp	= requests.get(SITEMAP_URL, timeout=10)
			resp.raise_for_status()
			root	= ET.fromstring(resp.text)
			urls	= [loc.text for loc in root.findall(".//{*}loc") if loc.text]
			print(f"[INFO] Raw XML parsed {len(urls)} URLs.")
			return [Document(page_content="", metadata={"source":u}) for u in urls]

# ────────────────────────────── Runner ──────────────────────────────
if __name__ == "__main__":
	while True:
		try:
			GringoCrawler().crawl()
			print("[SLEEP] 1 h until next crawl…")
			time.sleep(3600)
		except Exception as e:
			print(f"[ERROR] {e} – retry in 5 min")
			time.sleep(300)
