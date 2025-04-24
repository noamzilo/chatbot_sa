import os
import logging
from typing import List, Optional
import psycopg2
from psycopg2.extras import RealDictCursor
import numpy as np
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from openai import OpenAI
import uvicorn

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Initialize OpenAI client
api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    raise ValueError("OPENAI_API_KEY environment variable is not set")

client = OpenAI(api_key=api_key)

# Database connection
def get_db_connection():
    return psycopg2.connect(
        dbname=os.getenv("POSTGRES_DB"),
        user=os.getenv("POSTGRES_USER"),
        password=os.getenv("POSTGRES_PASSWORD"),
        host=os.getenv("POSTGRES_HOST"),
        port=os.getenv("POSTGRES_PORT")
    )

# FastAPI app
app = FastAPI(title="RAG API", description="API for querying the RAG database")

class QueryRequest(BaseModel):
    query: str
    limit: Optional[int] = 5

class DocumentResponse(BaseModel):
    id: int
    url: str
    title: Optional[str]
    content: str
    similarity: float

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

@app.post("/query", response_model=List[DocumentResponse])
async def query_documents(request: QueryRequest):
    try:
        # Get embedding for the query
        response = client.embeddings.create(
            input=request.query,
            model="text-embedding-3-small"
        )
        query_embedding = response.data[0].embedding

        # Query the database
        with get_db_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT 
                        id, url, title, content,
                        1 - (embedding <=> %s) as similarity
                    FROM gringo.documents
                    ORDER BY embedding <=> %s
                    LIMIT %s
                """, (query_embedding, query_embedding, request.limit))
                
                results = cur.fetchall()
                
        return [DocumentResponse(**doc) for doc in results]
    except Exception as e:
        logger.error(f"Error querying documents: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/documents/{document_id}", response_model=DocumentResponse)
async def get_document(document_id: int):
    try:
        with get_db_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT id, url, title, content, 1.0 as similarity
                    FROM gringo.documents
                    WHERE id = %s
                """, (document_id,))
                
                result = cur.fetchone()
                if not result:
                    raise HTTPException(status_code=404, detail="Document not found")
                
        return DocumentResponse(**result)
    except Exception as e:
        logger.error(f"Error fetching document: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000) 