import os
from typing import List, Dict, Any
import requests
from bs4 import BeautifulSoup
import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv
from langchain_community.document_loaders import SitemapLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter

load_dotenv()

class GringoCrawler:
    def __init__(self):
        self.db_connection = psycopg2.connect(
            dbname=os.getenv('POSTGRES_DB'),
            user=os.getenv('POSTGRES_USER'),
            password=os.getenv('POSTGRES_PASSWORD'),
            host=os.getenv('POSTGRES_HOST'),
            port=os.getenv('POSTGRES_PORT')
        )
        self._init_db()

    def _init_db(self):
        with self.db_connection.cursor() as cursor:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS gringo_pages (
                    id SERIAL PRIMARY KEY,
                    url TEXT UNIQUE,
                    content TEXT,
                    affiliate_links JSONB,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            self.db_connection.commit()

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
        """Main crawling function that processes the sitemap and stores content."""
        sitemap_url = "https://gringo.co.il/sitemap.xml"
        
        # Use LangChain's SitemapLoader
        loader = SitemapLoader(sitemap_url)
        documents = loader.load()
        
        # Split documents into chunks
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=200
        )
        chunks = text_splitter.split_documents(documents)
        
        # Process each chunk
        for chunk in chunks:
            url = chunk.metadata.get('source', '')
            content = chunk.page_content
            
            # Get the full page to extract affiliate links
            response = requests.get(url)
            soup = BeautifulSoup(response.text, 'lxml')
            affiliate_links = self._extract_affiliate_links(soup)
            
            # Store in database
            with self.db_connection.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO gringo_pages (url, content, affiliate_links)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (url) DO UPDATE
                    SET content = EXCLUDED.content,
                        affiliate_links = EXCLUDED.affiliate_links
                """, (url, content, affiliate_links))
            
            self.db_connection.commit()

    def __del__(self):
        if hasattr(self, 'db_connection'):
            self.db_connection.close()

if __name__ == "__main__":
    crawler = GringoCrawler()
    crawler.crawl() 