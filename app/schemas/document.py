from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class DocumentBase(BaseModel):
    filename: str
    original_filename: str
    file_type: str
    metadata: Optional[Dict[str, Any]] = None


class DocumentCreate(DocumentBase):
    file_path: str
    file_size: int
    content_hash: str
    raw_content: Optional[str] = None


class DocumentUpdate(BaseModel):
    raw_content: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    is_processed: Optional[bool] = None
    processing_status: Optional[str] = None
    processing_error: Optional[str] = None


class DocumentResponse(DocumentBase):
    id: UUID
    file_path: str
    file_size: int
    content_hash: str
    is_processed: bool
    processing_status: str
    processing_error: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class DocumentChunkBase(BaseModel):
    content: str
    chunk_index: int
    start_char: Optional[int] = None
    end_char: Optional[int] = None
    metadata: Optional[Dict[str, Any]] = None


class DocumentChunkCreate(DocumentChunkBase):
    document_id: UUID
    content_hash: str
    vector_id: Optional[str] = None


class DocumentChunkResponse(DocumentChunkBase):
    id: UUID
    document_id: UUID
    content_hash: str
    vector_id: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class SearchRequest(BaseModel):
    query: str
    limit: Optional[int] = Field(default=10, ge=1, le=100)
    similarity_threshold: Optional[float] = Field(default=0.7, ge=0.0, le=1.0)
    include_metadata: Optional[bool] = True


class SearchResult(BaseModel):
    chunk_id: UUID
    document_id: UUID
    content: str
    similarity_score: float
    metadata: Optional[Dict[str, Any]] = None
    document_filename: Optional[str] = None


class SearchResponse(BaseModel):
    query: str
    results: List[SearchResult]
    total_results: int
    processing_time_ms: float


class QARequest(BaseModel):
    question: str
    context_limit: Optional[int] = Field(default=5, ge=1, le=20)
    include_sources: Optional[bool] = True


class QAResponse(BaseModel):
    question: str
    answer: str
    confidence_score: Optional[float] = None
    sources: Optional[List[SearchResult]] = None
    completeness_score: Optional[float] = None
    processing_time_ms: float


class CompletenessCheckRequest(BaseModel):
    topic: str
    required_aspects: Optional[List[str]] = None


class CompletenessCheckResponse(BaseModel):
    topic: str
    completeness_score: float
    missing_aspects: List[str]
    covered_aspects: List[str]
    recommendations: List[str]