#!/usr/bin/env python3
"""
Gringo Parser
Step 2 → read uncached rows from gringo.raw_pages, parse, embed,
store in gringo.documents. Loops forever.
"""

import os, time, logging, psycopg2
from dotenv import load_dotenv
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings
from bs4 import BeautifulSoup

CHUNK_SIZE			= 1000
CHUNK_OVERLAP		= 200
BATCH_SLEEP			= 1800			# run every 30 min

PROJECT_ROOT	= os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

logging.basicConfig(
	level=logging.INFO,
	format="%(asctime)s [PARSER] %(levelname)s ▶ %(message)s",
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


splitter	= RecursiveCharacterTextSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)
embedder	= OpenAIEmbeddings(openai_api_key=os.getenv("OPENAI_API_KEY"))

def parse_once():
	db	= get_db()
	cur	= db.cursor()

	cur.execute(
		"""
		select rp.id, rp.url, rp.html
		from gringo.raw_pages rp
		left join gringo.documents d on rp.id = d.raw_page_id
		where d.id is null
		"""
	)
	rows = cur.fetchall()
	logging.info(f"Found {len(rows)} pages to embed")

	for raw_id, url, html in rows:
		soup	= BeautifulSoup(html, "lxml")
		title	= soup.title.string if soup.title else ""
		text	= soup.get_text("\n", strip=True)
		if not text:
			logging.warning(f"Skip empty {url}")
			continue

		chunks = splitter.split_text(text)
		vector = embedder.embed_query("\n\n".join(chunks))

		cur.execute(
			"""
			insert into gringo.documents(url, title, content, embedding, raw_page_id)
			values (%s,%s,%s,%s,%s)
			on conflict(url) do update
			set title=excluded.title,
				content=excluded.content,
				embedding=excluded.embedding,
				raw_page_id=excluded.raw_page_id,
				updated_at=current_timestamp
			""",
			(url, title, text, vector, raw_id),
		)
		db.commit()
		logging.info(f"Embedded {url}")

	cur.close()
	db.close()
	logging.info("Batch finished ✔")

if __name__ == "__main__":
	while True:
		try:
			parse_once()
			logging.info(f"Sleeping {BATCH_SLEEP//60} min…")
			time.sleep(BATCH_SLEEP)
		except Exception as e:
			logging.exception(e)
			time.sleep(300)
