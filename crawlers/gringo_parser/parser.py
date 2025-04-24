#!/usr/bin/env python3
"""
Gringo Parser
Step 2 → read uncached rows from gringo.raw_pages, parse, embed,
store in gringo.documents. Loops forever.
"""

import os, time, logging, psycopg2, json
from dotenv import load_dotenv
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings

CHUNK_SIZE          = 1000
CHUNK_OVERLAP       = 200
BATCH_SLEEP         = 7 * 24 * 3600          # run every week

PROJECT_ROOT    = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

logging.basicConfig(
	level=logging.INFO,
	format="%(asctime)s [PARSER] %(levelname)s ▶ %(message)s",
	datefmt="%Y-%m-%d %H:%M:%S",
)

def get_db(retries=10, delay=2):
	for i in range(retries):
		try:
			conn = psycopg2.connect(
				dbname  =os.getenv("POSTGRES_DB"),
				user    =os.getenv("POSTGRES_USER"),
				password=os.getenv("POSTGRES_PASSWORD"),
				host    =os.getenv("POSTGRES_HOST"),
				port    =os.getenv("POSTGRES_PORT"),
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

splitter    = RecursiveCharacterTextSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)
embedder    = OpenAIEmbeddings(openai_api_key=os.getenv("OPENAI_API_KEY"))

def parse_once():
	db  = get_db()
	cur = db.cursor()

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
		try:
			# Parse the JSON content from fetcher
			content_data = json.loads(html)
			title = content_data.get("title", "")
			text = content_data.get("content", "")
			
			if not text:
				logging.warning(f"Skip empty content for {url}")
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
		except json.JSONDecodeError as e:
			logging.error(f"Failed to parse JSON for {url}: {e}")
			continue
		except Exception as e:
			logging.error(f"Error processing {url}: {e}")
			continue

	cur.close()
	db.close()
	logging.info("Batch finished ✔")

if __name__ == "__main__":
	while True:
		try:
			parse_once()
			logging.info(f"Sleeping {BATCH_SLEEP//60} min…")
			time.sleep(BATCH_SLEEP)
		except Exception as e:
			logging.exception(e)
			time.sleep(300)
