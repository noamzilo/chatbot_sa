-- Rename html column to relevant_content in raw_pages
ALTER TABLE gringo.raw_pages RENAME COLUMN html TO relevant_content;

-- Add vector index to documents table for faster similarity search
CREATE INDEX IF NOT EXISTS idx_documents_embedding ON gringo.documents USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- Add comment to clarify table purposes
COMMENT ON TABLE gringo.raw_pages IS 'Stores raw content fetched from pages, with only relevant sections extracted';
COMMENT ON TABLE gringo.documents IS 'Stores parsed and embedded content for RAG vector search'; 