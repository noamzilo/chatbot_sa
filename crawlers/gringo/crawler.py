#!/usr/bin/env python3
"""
Gringo crawler v2
• Caches sitemap URLs in Postgres (TTL‑7 days)   • Respects MAX_PAGES for debug
• Caches raw HTML per URL                        • Embeds & stores into gringo.pages
"""

import os, time, requests, psycopg2
from typing import List
from bs4 import BeautifulSoup
from xml.etree import ElementTree as ET
from dotenv import load_dotenv
from psycopg2.extras import execute_values
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings
from langchain.docstore.document import Document
from tqdm import tqdm

# ───────────────────────── CONFIG ─────────────────────────
SITEMAP_URL	= "https://gringo.co.il/sitemap.xml"
SITEMAP_TTL	= 7 * 24 * 3600
CHUNK_SIZE	= 1000
CHUNK_OVERLAP	= 200
MAX_PAGES	= 1 #float("inf")
# ──────────────────────────────────────────────────────────
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

		print("[INIT] Checking DB.")
		with self.db.cursor() as cur:
			cur.execute("""
				select to_regclass('gringo.sitemap_cache'),
					to_regclass('gringo.pages'),
					to_regclass('gringo.affiliate_links'),
					to_regclass('gringo.page_affiliate_links')
			""")
			sitemap, pages, links, junction = cur.fetchone()
			if not all([sitemap, pages, links, junction]):
				print("[ERROR] One or more required tables are missing in DB:")
				print(f"  sitemap_cache:        {sitemap}")
				print(f"  pages:                {pages}")
				print(f"  affiliate_links:      {links}")
				print(f"  page_affiliate_links: {junction}")
				raise Exception("Missing required DB tables")
			else:
				print("[INIT] All required tables exist ✅")
		print("[INIT] DB OK.")
		print("[INIT] Loading OpenAI embeddings…")
		self.embedder = OpenAIEmbeddings(openai_api_key=os.getenv("OPENAI_API_KEY"))
		print("[INIT] Embeddings ready.")

	# ──────── Sitemap‑level caching (gringo.sitemap_cache) ────────
	def _load_sitemap_urls(self) -> List[str]:
		print("[DEBUG] Entered _load_sitemap_urls")

		with self.db.cursor() as cur:
			print("[DEBUG] Running sitemap_cache SELECT query")
			cur.execute("""
				select count(*) as n, max(fetched_at) as last_ts
				from gringo.sitemap_cache
			""")
			print("[DEBUG] Query returned")
			n_rows, last_ts = cur.fetchone()
			if n_rows and (time.time() - last_ts.timestamp() < SITEMAP_TTL):
				print(f"[CACHE] Sitemap cache hit – {n_rows} URLs, age {(time.time()-last_ts.timestamp()):.0f}s")
				cur.execute("select url from gringo.sitemap_cache order by url")
				rows = cur.fetchall()
				print(f"[DEBUG] Loaded {len(rows)} cached URLs")
				return [r[0] for r in rows]

		print("[CACHE] Refreshing sitemap cache…")
		resp = requests.get(SITEMAP_URL, timeout=10)
		print(f"[DEBUG] GET {SITEMAP_URL} = {resp.status_code}, {len(resp.text)} bytes")
		resp.raise_for_status()
		root = ET.fromstring(resp.text)
		urls = [loc.text for loc in root.findall(".//{*}loc") if loc.text]
		print(f"[INFO] Parsed {len(urls)} URLs from raw XML.")

		with self.db.cursor() as cur:
			execute_values(cur, """
				insert into gringo.sitemap_cache(url,fetched_at)
				values %s
				on conflict(url) do update
				set fetched_at = excluded.fetched_at
			""", [(u, ) for u in urls])
			self.db.commit()
			print("[DEBUG] Sitemap cache updated")

		return urls

	# ──────── Raw HTML caching (gringo.raw_pages) ────────
	def _get_or_insert_raw_html(self, url: str) -> tuple[int, str]:
		with self.db.cursor() as cur:
			cur.execute("select id, html, fetched_at from gringo.raw_pages where url=%s", (url,))
			row = cur.fetchone()
			if row and (time.time() - row[2].timestamp() < SITEMAP_TTL):
				return row[0], row[1]

			resp = requests.get(url, timeout=10)
			resp.raise_for_status()
			html = resp.text
			cur.execute("""
				insert into gringo.raw_pages(url,html,fetched_at)
				values(%s,%s,current_timestamp)
				on conflict(url) do update
				set html = excluded.html,
				    fetched_at = current_timestamp
				returning id
			""", (url, html))
			return cur.fetchone()[0], html

	def _get_or_create_affiliate(self, url:str,text:str)->int:
		with self.db.cursor() as cur:
			cur.execute("""
				insert into gringo.affiliate_links(url,link_text)
				values(%s,%s)
				on conflict(url,link_text) do update
				set updated_at=current_timestamp
				returning id
			""",(url,text))
			return cur.fetchone()[0]

	def _store_page(self,url,title,content,embedding,raw_id):
		with self.db.cursor() as cur:
			cur.execute("""
				insert into gringo.pages(url,title,content,embedding,raw_page_id)
				values(%s,%s,%s,%s,%s)
				on conflict(url) do update
				set title=excluded.title,
				    content=excluded.content,
				    embedding=excluded.embedding,
				    raw_page_id=excluded.raw_page_id,
				    updated_at=current_timestamp
				returning id
			""",(url,title,content,embedding,raw_id))
			return cur.fetchone()[0]

	def _link_page_affiliates(self,page_id,aff_ids):
		if not aff_ids: return
		with self.db.cursor() as cur:
			execute_values(cur,"""
				insert into gringo.page_affiliate_links(page_id,affiliate_id)
				values %s
				on conflict do nothing
			""",[(page_id,a) for a in aff_ids])

	# ───────────────────────────── Crawl ────────────────────────────
	def crawl(self):
		print("Starting crawler…")
		print("[CRAWLER] Loading sitemap...")
		urls = self._load_sitemap_urls()
		print(f"[CRAWLER] Got {len(urls)} URLs.")

		if MAX_PAGES != float("inf"):
			urls = urls[:int(MAX_PAGES)]
			print(f"[DEBUG] Limiting to first {len(urls)} URLs.")

		docs = [Document(page_content="", metadata={"source":u}) for u in urls]
		splitter = RecursiveCharacterTextSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)
		chunks   = splitter.split_documents(docs)
		print(f"[INFO] {len(chunks)} chunks to embed/store.")

		for chunk in tqdm(chunks, desc="Embed & Store"):
			url   = chunk.metadata["source"]
			raw_id, html = self._get_or_insert_raw_html(url)
			soup  = BeautifulSoup(html,"lxml")
			content = soup.get_text("\n", strip=True)
			if not content: continue

			embedding = self.embedder.embed_query(content)
			page_id   = self._store_page(url, soup.title.string if soup.title else "", content, embedding, raw_id)

			aff_ids = [
				self._get_or_create_affiliate(a["href"], a.get_text(strip=True))
				for a in soup.find_all("a", href=True)
				if any(k in a["href"].lower() for k in ("affiliate","partner"))
			]
			self._link_page_affiliates(page_id, aff_ids)
			self.db.commit()

		print("Crawler finished successfully.")

# ──────────────────────────── Runner ──────────────────────────────
if __name__ == "__main__":
	while True:
		try:
			GringoCrawler().crawl()
			print("[SLEEP] 1 h until next crawl…")
			time.sleep(3600)
		except Exception as e:
			print(f"[ERROR] {e} – retry in 5 min")
			time.sleep(300)
