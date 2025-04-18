import os
import time
from typing import List, Dict, Any
import requests
from bs4 import BeautifulSoup
import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv
from langchain_community.document_loaders import SitemapLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings
import xml.etree.ElementTree as ET
from langchain.docstore.document import Document

# Load environment variables from .env file in the project root
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), '.env'))

class GringoCrawler:
	def __init__(self):
		print("[INIT] Connecting to DB...")
		self.db_connection = psycopg2.connect(
			dbname=os.getenv('POSTGRES_DB'),
			user=os.getenv('POSTGRES_USER'),
			password=os.getenv('POSTGRES_PASSWORD'),
			host=os.getenv('POSTGRES_HOST'),
			port=os.getenv('POSTGRES_PORT')
		)
		print("[INIT] DB connection OK.")

		print("[INIT] Initializing OpenAI embeddings...")
		self.embeddings = OpenAIEmbeddings(openai_api_key=os.getenv('OPENAI_API_KEY'))
		print("[INIT] Embeddings initialized.")

	def _get_or_create_affiliate_link(self, url: str, link_text: str) -> int:
		"""Get existing affiliate link ID or create new one."""
		with self.db_connection.cursor() as cursor:
			cursor.execute("""
				INSERT INTO gringo.affiliate_links (url, link_text)
				VALUES (%s, %s)
				ON CONFLICT (url, link_text) DO UPDATE
				SET updated_at = CURRENT_TIMESTAMP
				RETURNING id
			""", (url, link_text))
			return cursor.fetchone()[0]

	def _store_page_with_embedding(self, url: str, title: str, content: str) -> int:
		try:
			embedding = self.embeddings.embed_query(content)
			assert embedding is not None, "Embedding returned None"
		except Exception as e:
			print(f"[ERROR] Embedding failed for {url}: {e}")
			return -1

		try:
			with self.db_connection.cursor() as cursor:
				cursor.execute("""
					INSERT INTO gringo.pages (url, title, content, embedding)
					VALUES (%s, %s, %s, %s)
					ON CONFLICT (url) DO UPDATE
					SET title = EXCLUDED.title,
						content = EXCLUDED.content,
						embedding = EXCLUDED.embedding,
						updated_at = CURRENT_TIMESTAMP
					RETURNING id
				""", (url, title, content, embedding))
				return cursor.fetchone()[0]
		except Exception as e:
			print(f"[ERROR] Insert failed for {url}: {e}")
			return -1

	def _link_page_to_affiliates(self, page_id: int, affiliate_ids: List[int]):
		"""Create links between page and its affiliate links."""
		if not affiliate_ids:
			return
			
		with self.db_connection.cursor() as cursor:
			execute_values(cursor, """
				INSERT INTO gringo.page_affiliate_links (page_id, affiliate_id)
				VALUES %s
				ON CONFLICT DO NOTHING
			""", [(page_id, aid) for aid in affiliate_ids])

	def _extract_affiliate_links(self, soup: BeautifulSoup) -> List[Dict[str, str]]:
		"""Extract affiliate links from the page content."""
		affiliate_links = []
		for link in soup.find_all('a', href=True):
			href = link.get('href', '')
			if 'affiliate' in href.lower() or 'partner' in href.lower():
				affiliate_links.append({
					'url': href,
					'text': link.get_text(strip=True)
				})
		return affiliate_links



	def crawl(self):
		print("Starting crawler...")

		sitemap_url = "https://gringo.co.il/sitemap.xml"
		print(f"[CRAWLER] Loading sitemap: {sitemap_url}")
		try:
			loader = SitemapLoader(sitemap_url)
			print("[CRAWLER] SitemapLoader initialized.")
			print("[CRAWLER] Calling loader.load()...")
			documents = loader.load()
			print(f"[CRAWLER] Loaded {len(documents)} documents via LangChain.")
		except Exception as e:
			print(f"[WARN] SitemapLoader failed: {e}")
			print("[CRAWLER] Falling back to raw XML fetch...")

			try:
				resp = requests.get(sitemap_url, timeout=10)
				resp.raise_for_status()
				print(f"[CRAWLER] Raw sitemap fetched, {len(resp.text)} bytes.")

				root = ET.fromstring(resp.text)
				urls = [elem.text for elem in root.findall(".//{*}loc") if elem.text]
				print(f"[CRAWLER] Parsed {len(urls)} URLs from raw XML.")

				# Wrap URLs in LangChain-compatible Document objects
				documents = [Document(page_content="", metadata={"source": url}) for url in urls]
			except Exception as e2:
				print(f"[ERROR] Raw sitemap fallback also failed: {e2}")
				return

		# Split documents into chunks
		print("[CRAWLER] Splitting documents into chunks...")
		text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
		try:
			chunks = text_splitter.split_documents(documents)
			print(f"[CRAWLER] Split into {len(chunks)} chunks.")
		except Exception as e:
			print(f"[ERROR] Text splitting failed: {e}")
			return

		# Process each chunk
		for i, chunk in enumerate(chunks):
			try:
				url = chunk.metadata.get('source', '')
				title = chunk.metadata.get('title', '')
				response = requests.get(url, timeout=10)
				soup = BeautifulSoup(response.text, "lxml")
				content = soup.get_text(separator="\n", strip=True)
				if not content:
					print(f"[SKIP] Empty content for URL: {url}")
					continue

				print(f"[{i+1}/{len(chunks)}] Processing {url}")

				response = requests.get(url, timeout=10)
				soup = BeautifulSoup(response.text, 'lxml')
				affiliate_links = self._extract_affiliate_links(soup)

				page_id = self._store_page_with_embedding(url, title, content)
				if page_id == -1:
					print(f"[WARN] Skipped {url} due to insert failure.")
					continue

				affiliate_ids = []
				for link in affiliate_links:
					affiliate_id = self._get_or_create_affiliate_link(link['url'], link['text'])
					affiliate_ids.append(affiliate_id)

				self._link_page_to_affiliates(page_id, affiliate_ids)

				try:
					self.db_connection.commit()
				except Exception as e:
					print(f"[ERROR] Commit failed for {url}: {e}")
			except Exception as e:
				print(f"[ERROR] Failed to process chunk {i+1}: {e}")

		print("Crawler finished.")


	def __del__(self):
		if hasattr(self, 'db_connection'):
			self.db_connection.close()

def main():
	while True:
		try:
			crawler = GringoCrawler()
			crawler.crawl()
			print("Waiting 1 hour before next run...")
			time.sleep(3600)
		except Exception as e:
			print(f"Error occurred: {e}")
			print("Retrying in 5 minutes...")
			time.sleep(300)

if __name__ == "__main__":
	main() 