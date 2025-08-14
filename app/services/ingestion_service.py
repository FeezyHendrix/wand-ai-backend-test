import asyncio
from typing import Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from loguru import logger

from app.models.document import Document, DocumentChunk
from app.schemas.document import DocumentCreate, DocumentChunkCreate
from app.services.document_processor import DocumentProcessor
from app.services.embedding_service import EmbeddingService
from app.core.config import get_settings

settings = get_settings()


class IngestionService:
    """Orchestrates document ingestion pipeline."""
    
    def __init__(self):
        self.document_processor = DocumentProcessor()
        self.embedding_service = EmbeddingService()
    
    async def ingest_document(
        self, 
        db: AsyncSession,
        file_content: bytes,
        filename: str,
        content_type: str,
        metadata: Optional[Dict] = None
    ) -> Tuple[Document, bool]:
        """
        Ingest a document through the complete pipeline.
        Returns (document, is_new) tuple.
        """
        try:
            # Validate file type
            file_type = self.document_processor.get_file_type_from_content_type(content_type)
            if not file_type:
                raise ValueError(f"Unsupported file type: {content_type}")
            
            # Save file and calculate hash
            file_path, content_hash = await self.document_processor.save_uploaded_file(
                file_content, filename
            )
            
            # Check if document already exists
            existing_doc = await self._get_document_by_hash(db, content_hash)
            if existing_doc:
                logger.info(f"Document already exists: {existing_doc.id}")
                return existing_doc, False
            
            # Create document record
            document_data = DocumentCreate(
                filename=filename,
                original_filename=filename,
                file_path=file_path,
                file_size=len(file_content),
                file_type=file_type,
                content_hash=content_hash,
                metadata=metadata
            )
            
            document = Document(**document_data.dict())
            db.add(document)
            await db.commit()
            await db.refresh(document)
            
            # Process document asynchronously
            asyncio.create_task(self._process_document_async(document.id, db))
            
            logger.info(f"Started ingestion for document: {document.id}")
            return document, True
            
        except Exception as e:
            logger.error(f"Error ingesting document {filename}: {str(e)}")
            await db.rollback()
            raise
    
    async def _process_document_async(self, document_id: UUID, db: AsyncSession):
        """Process document in background."""
        try:
            # Update status to processing
            await self._update_processing_status(db, document_id, "processing")
            
            # Get document
            document = await self._get_document_by_id(db, document_id)
            if not document:
                raise ValueError(f"Document not found: {document_id}")
            
            # Extract text
            raw_content = await self.document_processor.process_large_file(
                document.file_path, document.file_type
            )
            
            # Update document with raw content
            await self._update_document_content(db, document_id, raw_content)
            
            # Create chunks
            chunks_data = self.document_processor.chunk_text(
                raw_content, 
                metadata={
                    "document_id": str(document_id),
                    "filename": document.filename,
                    "file_type": document.file_type
                }
            )
            
            if not chunks_data:
                await self._update_processing_status(
                    db, document_id, "completed", "No content to process"
                )
                return
            
            # Store chunks and generate embeddings
            await self._store_chunks_with_embeddings(db, document_id, chunks_data)
            
            # Mark as completed
            await self._update_processing_status(db, document_id, "completed")
            
            logger.info(f"Successfully processed document: {document_id}")
            
        except Exception as e:
            error_msg = f"Error processing document {document_id}: {str(e)}"
            logger.error(error_msg)
            await self._update_processing_status(db, document_id, "failed", error_msg)
    
    async def _store_chunks_with_embeddings(
        self, 
        db: AsyncSession, 
        document_id: UUID, 
        chunks_data: List[Dict]
    ):
        """Store document chunks and generate embeddings."""
        try:
            # Prepare texts and metadata for embedding
            texts = [chunk["content"] for chunk in chunks_data]
            metadatas = []
            
            for i, chunk in enumerate(chunks_data):
                metadata = chunk["metadata"].copy()
                metadata.update({
                    "chunk_index": chunk["chunk_index"],
                    "start_char": chunk.get("start_char"),
                    "end_char": chunk.get("end_char")
                })
                metadatas.append(metadata)
            
            # Generate embeddings and store in vector DB
            vector_ids = await self.embedding_service.add_documents(
                texts=texts,
                metadatas=metadatas
            )
            
            # Store chunks in database
            chunk_records = []
            for i, chunk in enumerate(chunks_data):
                chunk_create = DocumentChunkCreate(
                    document_id=document_id,
                    content=chunk["content"],
                    chunk_index=chunk["chunk_index"],
                    start_char=chunk.get("start_char"),
                    end_char=chunk.get("end_char"),
                    content_hash=self.document_processor.calculate_content_hash(
                        chunk["content"]
                    ),
                    vector_id=vector_ids[i],
                    metadata=chunk["metadata"]
                )
                
                chunk_record = DocumentChunk(**chunk_create.dict())
                chunk_records.append(chunk_record)
            
            db.add_all(chunk_records)
            await db.commit()
            
            logger.info(f"Stored {len(chunk_records)} chunks for document {document_id}")
            
        except Exception as e:
            logger.error(f"Error storing chunks for document {document_id}: {str(e)}")
            raise
    
    async def _get_document_by_hash(self, db: AsyncSession, content_hash: str) -> Optional[Document]:
        """Get document by content hash."""
        result = await db.execute(
            select(Document).where(Document.content_hash == content_hash)
        )
        return result.scalar_one_or_none()
    
    async def _get_document_by_id(self, db: AsyncSession, document_id: UUID) -> Optional[Document]:
        """Get document by ID."""
        result = await db.execute(
            select(Document).where(Document.id == document_id)
        )
        return result.scalar_one_or_none()
    
    async def _update_processing_status(
        self, 
        db: AsyncSession, 
        document_id: UUID, 
        status: str, 
        error_msg: Optional[str] = None
    ):
        """Update document processing status."""
        update_data = {
            "processing_status": status,
            "is_processed": status == "completed"
        }
        
        if error_msg:
            update_data["processing_error"] = error_msg
        
        await db.execute(
            update(Document)
            .where(Document.id == document_id)
            .values(**update_data)
        )
        await db.commit()
    
    async def _update_document_content(
        self, 
        db: AsyncSession, 
        document_id: UUID, 
        content: str
    ):
        """Update document with extracted content."""
        await db.execute(
            update(Document)
            .where(Document.id == document_id)
            .values(raw_content=content)
        )
        await db.commit()
    
    async def reprocess_document(self, db: AsyncSession, document_id: UUID) -> bool:
        """Reprocess an existing document."""
        try:
            document = await self._get_document_by_id(db, document_id)
            if not document:
                raise ValueError(f"Document not found: {document_id}")
            
            # Delete existing chunks and embeddings
            await self._cleanup_document_chunks(db, document_id)
            
            # Restart processing
            asyncio.create_task(self._process_document_async(document_id, db))
            
            logger.info(f"Started reprocessing for document: {document_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error reprocessing document {document_id}: {str(e)}")
            raise
    
    async def _cleanup_document_chunks(self, db: AsyncSession, document_id: UUID):
        """Clean up chunks and embeddings for a document."""
        # Get chunk vector IDs
        result = await db.execute(
            select(DocumentChunk.vector_id)
            .where(DocumentChunk.document_id == document_id)
        )
        vector_ids = [row[0] for row in result.fetchall() if row[0]]
        
        # Delete from vector store
        if vector_ids:
            for vector_id in vector_ids:
                await self.embedding_service.delete_document(vector_id)
        
        # Delete chunk records
        await db.execute(
            select(DocumentChunk).where(DocumentChunk.document_id == document_id)
        )
        await db.commit()