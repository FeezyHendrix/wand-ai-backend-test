import time
from typing import Dict, List, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from loguru import logger

from app.models.document import Document, DocumentChunk
from app.schemas.document import SearchRequest, SearchResult, SearchResponse
from app.services.embedding_service import EmbeddingService
from app.core.config import get_settings

settings = get_settings()


class SearchService:
    """Handles semantic search operations."""
    
    def __init__(self):
        self.embedding_service = EmbeddingService()
    
    async def semantic_search(
        self, 
        db: AsyncSession, 
        search_request: SearchRequest
    ) -> SearchResponse:
        """Perform semantic search across the knowledge base."""
        start_time = time.time()
        
        try:
            # Search in vector store
            vector_results = await self.embedding_service.search_similar(
                query=search_request.query,
                limit=search_request.limit * 2,  # Get more results to filter
                where=None
            )
            
            # Filter by similarity threshold and get document info
            filtered_results = []
            for i, (vector_id, distance) in enumerate(
                zip(vector_results["ids"], vector_results["distances"])
            ):
                similarity_score = self.embedding_service.convert_distance_to_similarity(distance)
                
                if similarity_score >= search_request.similarity_threshold:
                    # Get chunk and document info from database
                    chunk_info = await self._get_chunk_info(db, vector_id)
                    if chunk_info:
                        search_result = SearchResult(
                            chunk_id=chunk_info["chunk_id"],
                            document_id=chunk_info["document_id"],
                            content=vector_results["documents"][i],
                            similarity_score=round(similarity_score, 4),
                            metadata=vector_results["metadatas"][i] if search_request.include_metadata else None,
                            document_filename=chunk_info.get("filename")
                        )
                        filtered_results.append(search_result)
            
            # Sort by similarity score and limit results
            filtered_results.sort(key=lambda x: x.similarity_score, reverse=True)
            final_results = filtered_results[:search_request.limit]
            
            processing_time = (time.time() - start_time) * 1000
            
            return SearchResponse(
                query=search_request.query,
                results=final_results,
                total_results=len(final_results),
                processing_time_ms=round(processing_time, 2)
            )
            
        except Exception as e:
            logger.error(f"Error performing semantic search: {str(e)}")
            raise
    
    async def _get_chunk_info(self, db: AsyncSession, vector_id: str) -> Optional[Dict]:
        """Get chunk and document information from database."""
        try:
            result = await db.execute(
                select(
                    DocumentChunk.id.label("chunk_id"),
                    DocumentChunk.document_id,
                    Document.filename
                )
                .join(Document, DocumentChunk.document_id == Document.id)
                .where(DocumentChunk.vector_id == vector_id)
            )
            
            row = result.fetchone()
            if row:
                return {
                    "chunk_id": row.chunk_id,
                    "document_id": row.document_id,
                    "filename": row.filename
                }
            return None
            
        except Exception as e:
            logger.error(f"Error getting chunk info for vector_id {vector_id}: {str(e)}")
            return None
    
    async def search_by_document(
        self, 
        db: AsyncSession,
        document_id: UUID,
        query: str,
        limit: int = 10
    ) -> List[SearchResult]:
        """Search within a specific document."""
        try:
            # Get document chunks
            result = await db.execute(
                select(DocumentChunk)
                .where(DocumentChunk.document_id == document_id)
            )
            chunks = result.scalars().all()
            
            if not chunks:
                return []
            
            # Get vector IDs
            vector_ids = [chunk.vector_id for chunk in chunks if chunk.vector_id]
            
            if not vector_ids:
                return []
            
            # Search in vector store with document filter
            vector_results = await self.embedding_service.search_similar(
                query=query,
                limit=limit,
                where={"document_id": str(document_id)}
            )
            
            # Convert to search results
            search_results = []
            for i, (vector_id, distance) in enumerate(
                zip(vector_results["ids"], vector_results["distances"])
            ):
                similarity_score = self.embedding_service.convert_distance_to_similarity(distance)
                
                # Find corresponding chunk
                chunk = next(
                    (c for c in chunks if c.vector_id == vector_id), 
                    None
                )
                
                if chunk:
                    search_result = SearchResult(
                        chunk_id=chunk.id,
                        document_id=chunk.document_id,
                        content=vector_results["documents"][i],
                        similarity_score=round(similarity_score, 4),
                        metadata=vector_results["metadatas"][i],
                        document_filename=None  # Already know it's from this document
                    )
                    search_results.append(search_result)
            
            return search_results
            
        except Exception as e:
            logger.error(f"Error searching in document {document_id}: {str(e)}")
            raise
    
    async def get_similar_documents(
        self, 
        db: AsyncSession,
        document_id: UUID,
        limit: int = 5
    ) -> List[SearchResult]:
        """Find documents similar to the given document."""
        try:
            # Get a representative chunk from the document
            result = await db.execute(
                select(DocumentChunk)
                .where(DocumentChunk.document_id == document_id)
                .order_by(DocumentChunk.chunk_index)
                .limit(1)
            )
            
            representative_chunk = result.scalar_one_or_none()
            if not representative_chunk:
                return []
            
            # Use the chunk content as query
            search_request = SearchRequest(
                query=representative_chunk.content[:500],  # Use first 500 chars
                limit=limit + 1,  # +1 to exclude the same document
                similarity_threshold=0.5
            )
            
            results = await self.semantic_search(db, search_request)
            
            # Filter out the same document
            filtered_results = [
                r for r in results.results 
                if r.document_id != document_id
            ]
            
            return filtered_results[:limit]
            
        except Exception as e:
            logger.error(f"Error finding similar documents for {document_id}: {str(e)}")
            raise
    
    async def get_search_suggestions(
        self, 
        db: AsyncSession,
        partial_query: str,
        limit: int = 5
    ) -> List[str]:
        """Get search suggestions based on partial query."""
        try:
            if len(partial_query) < 3:
                return []
            
            # Perform a quick search
            search_request = SearchRequest(
                query=partial_query,
                limit=limit * 2,
                similarity_threshold=0.3
            )
            
            results = await self.semantic_search(db, search_request)
            
            # Extract key phrases from results
            suggestions = []
            for result in results.results:
                # Simple keyword extraction (in production, use more sophisticated NLP)
                words = result.content.split()
                for i in range(len(words) - 2):
                    phrase = " ".join(words[i:i+3])
                    if partial_query.lower() in phrase.lower() and phrase not in suggestions:
                        suggestions.append(phrase)
                        if len(suggestions) >= limit:
                            break
                
                if len(suggestions) >= limit:
                    break
            
            return suggestions
            
        except Exception as e:
            logger.error(f"Error getting search suggestions: {str(e)}")
            return []
    
    async def get_trending_searches(self, db: AsyncSession, limit: int = 10) -> List[str]:
        """Get trending search queries (placeholder implementation)."""
        # In a production system, this would analyze search logs
        # For now, return some common search patterns
        return [
            "machine learning",
            "data analysis",
            "API documentation",
            "best practices",
            "troubleshooting",
            "configuration",
            "performance optimization",
            "security guidelines",
            "deployment process",
            "testing strategies"
        ][:limit]