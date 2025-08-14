import asyncio
from typing import List, Optional, Dict, Any
import uuid

import chromadb
from chromadb.config import Settings as ChromaSettings
from sentence_transformers import SentenceTransformer
from loguru import logger
import numpy as np

from app.core.config import get_settings

settings = get_settings()


class EmbeddingService:
    """Handles text embedding generation and vector storage."""
    
    def __init__(self):
        self.model = SentenceTransformer(settings.embedding_model)
        self.chroma_client = chromadb.PersistentClient(
            path=settings.chroma_persist_directory,
            settings=ChromaSettings(anonymized_telemetry=False)
        )
        self.collection_name = "knowledge_base"
        self._initialize_collection()
    
    def _initialize_collection(self):
        """Initialize ChromaDB collection."""
        try:
            self.collection = self.chroma_client.get_collection(
                name=self.collection_name
            )
            logger.info(f"Connected to existing collection: {self.collection_name}")
        except ValueError:
            # Collection doesn't exist, create it
            self.collection = self.chroma_client.create_collection(
                name=self.collection_name,
                metadata={"description": "Knowledge base document embeddings"}
            )
            logger.info(f"Created new collection: {self.collection_name}")
    
    async def generate_embeddings(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for a list of texts."""
        try:
            # Run embedding generation in thread pool to avoid blocking
            loop = asyncio.get_event_loop()
            embeddings = await loop.run_in_executor(
                None, 
                self.model.encode, 
                texts
            )
            return embeddings.tolist()
        except Exception as e:
            logger.error(f"Error generating embeddings: {str(e)}")
            raise
    
    async def add_documents(
        self, 
        texts: List[str], 
        metadatas: List[Dict[str, Any]], 
        ids: Optional[List[str]] = None
    ) -> List[str]:
        """Add documents to the vector store."""
        if not texts:
            return []
        
        # Generate IDs if not provided
        if ids is None:
            ids = [str(uuid.uuid4()) for _ in texts]
        
        try:
            # Generate embeddings
            embeddings = await self.generate_embeddings(texts)
            
            # Add to ChromaDB
            self.collection.add(
                embeddings=embeddings,
                documents=texts,
                metadatas=metadatas,
                ids=ids
            )
            
            logger.info(f"Added {len(texts)} documents to vector store")
            return ids
            
        except Exception as e:
            logger.error(f"Error adding documents to vector store: {str(e)}")
            raise
    
    async def search_similar(
        self, 
        query: str, 
        limit: int = 10, 
        where: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Search for similar documents."""
        try:
            # Generate query embedding
            query_embeddings = await self.generate_embeddings([query])
            
            # Search in ChromaDB
            results = self.collection.query(
                query_embeddings=query_embeddings,
                n_results=limit,
                where=where,
                include=["documents", "metadatas", "distances"]
            )
            
            return {
                "ids": results["ids"][0] if results["ids"] else [],
                "documents": results["documents"][0] if results["documents"] else [],
                "metadatas": results["metadatas"][0] if results["metadatas"] else [],
                "distances": results["distances"][0] if results["distances"] else []
            }
            
        except Exception as e:
            logger.error(f"Error searching similar documents: {str(e)}")
            raise
    
    async def update_document(
        self, 
        doc_id: str, 
        text: str, 
        metadata: Dict[str, Any]
    ) -> bool:
        """Update a document in the vector store."""
        try:
            # Generate new embedding
            embeddings = await self.generate_embeddings([text])
            
            # Update in ChromaDB
            self.collection.update(
                ids=[doc_id],
                embeddings=embeddings,
                documents=[text],
                metadatas=[metadata]
            )
            
            logger.info(f"Updated document {doc_id} in vector store")
            return True
            
        except Exception as e:
            logger.error(f"Error updating document {doc_id}: {str(e)}")
            raise
    
    async def delete_document(self, doc_id: str) -> bool:
        """Delete a document from the vector store."""
        try:
            self.collection.delete(ids=[doc_id])
            logger.info(f"Deleted document {doc_id} from vector store")
            return True
            
        except Exception as e:
            logger.error(f"Error deleting document {doc_id}: {str(e)}")
            raise
    
    async def delete_documents_by_metadata(self, where: Dict[str, Any]) -> bool:
        """Delete documents matching metadata criteria."""
        try:
            # First, get the IDs of documents to delete
            results = self.collection.get(
                where=where,
                include=["metadatas"]
            )
            
            if results["ids"]:
                self.collection.delete(where=where)
                logger.info(f"Deleted {len(results['ids'])} documents matching criteria")
            
            return True
            
        except Exception as e:
            logger.error(f"Error deleting documents by metadata: {str(e)}")
            raise
    
    def get_collection_stats(self) -> Dict[str, Any]:
        """Get statistics about the vector collection."""
        try:
            count = self.collection.count()
            return {
                "total_documents": count,
                "collection_name": self.collection_name,
                "embedding_model": settings.embedding_model,
                "embedding_dimension": settings.embedding_dimension
            }
        except Exception as e:
            logger.error(f"Error getting collection stats: {str(e)}")
            return {"error": str(e)}
    
    def convert_distance_to_similarity(self, distance: float) -> float:
        """Convert ChromaDB distance to similarity score (0-1)."""
        # ChromaDB uses squared L2 distance, convert to similarity
        # For normalized embeddings, distance ranges from 0 to 4
        # Convert to similarity where lower distance = higher similarity
        return max(0.0, 1.0 - (distance / 4.0))