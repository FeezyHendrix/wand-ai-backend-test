from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.document import (
    DocumentResponse, SearchRequest, SearchResponse, QARequest, 
    QAResponse, CompletenessCheckRequest, CompletenessCheckResponse
)
from app.services.ingestion_service import IngestionService
from app.services.search_service import SearchService
from app.services.qa_service import QAService
from app.core.config import get_settings

settings = get_settings()

router = APIRouter()

# Service instances
ingestion_service = IngestionService()
search_service = SearchService()
qa_service = QAService()


@router.post("/documents/upload", response_model=DocumentResponse)
async def upload_document(
    file: UploadFile = File(...),
    metadata: str = Form("{}"),
    db: AsyncSession = Depends(get_db)
):
    """Upload and ingest a document into the knowledge base."""
    try:
        # Validate file type
        if not ingestion_service.document_processor.is_supported_file_type(file.content_type):
            raise HTTPException(
                status_code=400, 
                detail=f"Unsupported file type: {file.content_type}"
            )
        
        # Validate file size
        content = await file.read()
        max_size = settings.max_file_size_mb * 1024 * 1024
        if len(content) > max_size:
            raise HTTPException(
                status_code=400,
                detail=f"File size exceeds {settings.max_file_size_mb}MB limit"
            )
        
        # Parse metadata
        import json
        try:
            metadata_dict = json.loads(metadata) if metadata != "{}" else {}
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid metadata JSON")
        
        # Ingest document
        document, is_new = await ingestion_service.ingest_document(
            db=db,
            file_content=content,
            filename=file.filename,
            content_type=file.content_type,
            metadata=metadata_dict
        )
        
        return DocumentResponse.from_orm(document)
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error uploading document: {str(e)}")


@router.post("/search", response_model=SearchResponse)
async def semantic_search(
    search_request: SearchRequest,
    db: AsyncSession = Depends(get_db)
):
    """Perform semantic search across the knowledge base."""
    try:
        return await search_service.semantic_search(db, search_request)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Search error: {str(e)}")


@router.post("/qa", response_model=QAResponse)
async def question_answering(
    qa_request: QARequest,
    db: AsyncSession = Depends(get_db)
):
    """Answer questions using the knowledge base."""
    try:
        return await qa_service.answer_question(db, qa_request)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"QA error: {str(e)}")


@router.post("/completeness", response_model=CompletenessCheckResponse)
async def check_completeness(
    request: CompletenessCheckRequest,
    db: AsyncSession = Depends(get_db)
):
    """Check knowledge base completeness for a topic."""
    try:
        return await qa_service.check_completeness(db, request)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Completeness check error: {str(e)}")


@router.get("/documents/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """Get document information by ID."""
    try:
        from sqlalchemy import select
        from app.models.document import Document
        
        result = await db.execute(
            select(Document).where(Document.id == document_id)
        )
        document = result.scalar_one_or_none()
        
        if not document:
            raise HTTPException(status_code=404, detail="Document not found")
        
        return DocumentResponse.from_orm(document)
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving document: {str(e)}")


@router.post("/documents/{document_id}/reprocess")
async def reprocess_document(
    document_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """Reprocess a document to update its embeddings."""
    try:
        success = await ingestion_service.reprocess_document(db, document_id)
        if success:
            return {"message": "Document reprocessing started"}
        else:
            raise HTTPException(status_code=400, detail="Failed to start reprocessing")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Reprocessing error: {str(e)}")


@router.get("/documents/{document_id}/search")
async def search_in_document(
    document_id: UUID,
    query: str,
    limit: int = 10,
    db: AsyncSession = Depends(get_db)
):
    """Search within a specific document."""
    try:
        results = await search_service.search_by_document(db, document_id, query, limit)
        return {"results": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Document search error: {str(e)}")


@router.get("/documents/{document_id}/similar")
async def get_similar_documents(
    document_id: UUID,
    limit: int = 5,
    db: AsyncSession = Depends(get_db)
):
    """Find documents similar to the given document."""
    try:
        results = await search_service.get_similar_documents(db, document_id, limit)
        return {"similar_documents": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Similar documents error: {str(e)}")


@router.get("/search/suggestions")
async def get_search_suggestions(
    q: str,
    limit: int = 5,
    db: AsyncSession = Depends(get_db)
):
    """Get search suggestions based on partial query."""
    try:
        suggestions = await search_service.get_search_suggestions(db, q, limit)
        return {"suggestions": suggestions}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Suggestions error: {str(e)}")


@router.get("/stats")
async def get_knowledge_base_stats(db: AsyncSession = Depends(get_db)):
    """Get knowledge base statistics."""
    try:
        from sqlalchemy import select, func
        from app.models.document import Document, DocumentChunk
        
        # Get document count
        doc_result = await db.execute(select(func.count(Document.id)))
        doc_count = doc_result.scalar()
        
        # Get chunk count
        chunk_result = await db.execute(select(func.count(DocumentChunk.id)))
        chunk_count = chunk_result.scalar()
        
        # Get processed document count
        processed_result = await db.execute(
            select(func.count(Document.id)).where(Document.is_processed == True)
        )
        processed_count = processed_result.scalar()
        
        # Get vector store stats
        vector_stats = ingestion_service.embedding_service.get_collection_stats()
        
        return {
            "total_documents": doc_count,
            "processed_documents": processed_count,
            "total_chunks": chunk_count,
            "vector_store": vector_stats,
            "processing_rate": round(processed_count / max(doc_count, 1) * 100, 2)
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Stats error: {str(e)}")


@router.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "services": {
            "database": "ok",
            "vector_store": "ok",
            "embedding_model": settings.embedding_model
        }
    }