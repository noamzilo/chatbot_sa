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
                # First check total documents with embeddings
                cur.execute("SELECT COUNT(*) as count FROM gringo.documents WHERE embedding IS NOT NULL")
                total_docs = cur.fetchone()['count']
                logger.info(f"Total documents with embeddings: {total_docs}")
                
                # Now execute the similarity search
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
                
                # Process and truncate documents to stay within token limits
                processed_results = []
                total_tokens = 0
                max_tokens_per_doc = 2000  # Limit tokens per document
                
                for doc in results:
                    # Truncate content if too long
                    content = doc['content']
                    if len(content.split()) > max_tokens_per_doc:
                        content = ' '.join(content.split()[:max_tokens_per_doc]) + "..."
                    
                    processed_doc = {
                        'id': doc['id'],
                        'url': doc['url'],
                        'title': doc['title'],
                        'content': content,
                        'similarity': doc['similarity']
                    }
                    processed_results.append(processed_doc)
                
                return [DocumentResponse(**doc) for doc in processed_results]
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
        logger.info(f"Starting RAG pipeline for query: {request.query}")
        
        # Get similar documents
        documents = get_similar_documents(request.query, request.limit)
        logger.info(f"Retrieved {len(documents)} relevant documents")
        
        if not documents:
            logger.warning("No relevant documents found for query")
            return RAGResponse(
                answer="I couldn't find any relevant information to answer your question.",
                sources=[]
            )

        # Format documents for context, ensuring we stay within token limits
        context_parts = []
        total_tokens = 0
        max_context_tokens = 8000  # Conservative limit for context
        
        for doc in documents:
            doc_tokens = len(doc.content.split())
            if total_tokens + doc_tokens > max_context_tokens:
                # Truncate the document if adding it would exceed the limit
                remaining_tokens = max_context_tokens - total_tokens
                if remaining_tokens > 0:
                    truncated_content = ' '.join(doc.content.split()[:remaining_tokens]) + "..."
                    context_parts.append(f"Source {len(context_parts)+1} (URL: {doc.url}):\n{truncated_content}")
                break
            else:
                context_parts.append(f"Source {len(context_parts)+1} (URL: {doc.url}):\n{doc.content}")
                total_tokens += doc_tokens

        context = "\n\n".join(context_parts)
        logger.info(f"Formatted context with {len(context_parts)} sources, total tokens: {total_tokens}")

        # Create RAG prompt with explicit language handling
        prompt = ChatPromptTemplate.from_messages([
            ("system", """You are a helpful assistant that answers questions based on the provided context.
            Generate a clear, concise answer in your own words based on the context.
            Do not directly quote or reference the sources in your answer.
            If the answer cannot be found in the context, say "I couldn't find enough information to answer that question."
            IMPORTANT: Always answer in the same language as the question and context. If the context is in Hebrew, answer in Hebrew.
            Keep your answer focused and to the point."""),
            ("human", """Context (in {context_language}):
            {context}

            Question (in {question_language}): {question}""")
        ])

        # Create RAG chain
        chain = (
            {
                "context": lambda _: context,
                "context_language": lambda _: "Hebrew" if any('\u0590' <= c <= '\u05FF' for c in context) else "English",
                "question_language": lambda x: "Hebrew" if any('\u0590' <= c <= '\u05FF' for c in x) else "English",
                "question": RunnablePassthrough()
            }
            | prompt
            | llm
            | StrOutputParser()
        )

        # Generate answer
        logger.info("Generating answer using RAG chain...")
        try:
            answer = chain.invoke(request.query)
            logger.info(f"Generated answer: {answer}")
        except Exception as e:
            if "context_length_exceeded" in str(e):
                logger.error("Token limit exceeded, retrying with reduced context")
                # If we hit the token limit, try with fewer documents
                if len(documents) > 1:
                    return await query_documents(QueryRequest(query=request.query, limit=len(documents)-1))
                else:
                    raise HTTPException(status_code=400, detail="The query is too long to process. Please try a shorter query.")
            raise
        
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