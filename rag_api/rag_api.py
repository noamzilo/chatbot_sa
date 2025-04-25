import os
import logging
from typing import List, Optional
import psycopg2
from psycopg2.extras import RealDictCursor
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from openai import OpenAI
import uvicorn
from langchain_openai import ChatOpenAI
from langchain.prompts import ChatPromptTemplate
from langchain.schema.runnable import RunnablePassthrough
from langchain.schema.output_parser import StrOutputParser

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
llm = ChatOpenAI(model="gpt-3.5-turbo", temperature=0)

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

class RAGResponse(BaseModel):
    answer: str
    sources: List[DocumentResponse]

def get_similar_documents(query: str, limit: int) -> List[DocumentResponse]:
    try:
        logger.info(f"Received query request: {query} with limit {limit}")
        
        # Get embedding for the query
        logger.info("Generating embedding for query...")
        response = client.embeddings.create(
            input=query,
            model="text-embedding-3-small"
        )
        query_embedding = response.data[0].embedding
        logger.info(f"Generated embedding of length: {len(query_embedding)}")

        # Convert embedding to string format for pgvector
        embedding_str = "[" + ",".join(map(str, query_embedding)) + "]"
        logger.info(f"Converted embedding to string format: {embedding_str[:100]}...")

        # Query the database
        logger.info("Querying database for similar documents...")
        with get_db_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                logger.info("Executing similarity search query...")
                cur.execute("""
                    SELECT 
                        id, url, title, content,
                        1 - (embedding <=> %s::vector) as similarity
                    FROM gringo.documents
                    WHERE embedding IS NOT NULL
                    ORDER BY similarity DESC
                    LIMIT %s
                """, (embedding_str, limit))
                
                results = cur.fetchall()
                logger.info(f"Found {len(results)} matching documents")
                if results:
                    logger.info(f"Similarity scores: {[r['similarity'] for r in results]}")
                
        return [DocumentResponse(**doc) for doc in results]
    except Exception as e:
        logger.error(f"Error querying documents: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

@app.post("/results", response_model=List[DocumentResponse])
async def get_results(request: QueryRequest):
    """Endpoint to get raw similarity search results"""
    return get_similar_documents(request.query, request.limit)

@app.post("/query", response_model=RAGResponse)
async def query_documents(request: QueryRequest):
    """Endpoint that uses RAG to generate an answer based on the retrieved documents"""
    try:
        # Get similar documents
        documents = get_similar_documents(request.query, request.limit)
        
        if not documents:
            return RAGResponse(
                answer="I couldn't find any relevant information to answer your question.",
                sources=[]
            )

        # Format documents for context
        context = "\n\n".join([
            f"Source {i+1} (URL: {doc.url}):\n{doc.content}"
            for i, doc in enumerate(documents)
        ])

        # Create RAG prompt
        prompt = ChatPromptTemplate.from_messages([
            ("system", """You are a helpful assistant that answers questions based on the provided context.
            If the answer cannot be found in the context, say "I couldn't find enough information to answer that question."
            Always cite your sources using the source numbers provided.
            Answer in the same language as the question."""),
            ("human", """Context:
            {context}

            Question: {question}""")
        ])

        # Create RAG chain
        chain = (
            {"context": lambda _: context, "question": RunnablePassthrough()}
            | prompt
            | llm
            | StrOutputParser()
        )

        # Generate answer
        answer = chain.invoke(request.query)
        
        return RAGResponse(
            answer=answer,
            sources=documents
        )
    except Exception as e:
        logger.error(f"Error in RAG pipeline: {str(e)}", exc_info=True)
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