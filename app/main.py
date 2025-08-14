import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from app.api.endpoints import router
from app.core.config import get_settings
from app.services.incremental_indexer import IncrementalIndexer

settings = get_settings()

# Global indexer instance
indexer = IncrementalIndexer()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan management."""
    logger.info("Starting AI Knowledge Base API")
    
    # Add some default watch directories (customize as needed)
    indexer.add_watch_directory("./documents")
    indexer.add_watch_directory("./uploads")
    
    # Start incremental indexing in background
    indexing_task = asyncio.create_task(indexer.start_watching())
    
    yield
    
    # Cleanup
    logger.info("Shutting down AI Knowledge Base API")
    indexing_task.cancel()
    try:
        await indexing_task
    except asyncio.CancelledError:
        pass


app = FastAPI(
    title="AI-Powered Knowledge Base",
    description="Advanced document search and Q&A system with semantic understanding",
    version="1.0.0",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routes
app.include_router(router, prefix="/api/v1")


@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "name": "AI-Powered Knowledge Base",
        "version": "1.0.0",
        "description": "Document ingestion, semantic search, and intelligent Q&A system",
        "endpoints": {
            "upload": "/api/v1/documents/upload",
            "search": "/api/v1/search",
            "qa": "/api/v1/qa",
            "completeness": "/api/v1/completeness",
            "stats": "/api/v1/stats",
            "health": "/api/v1/health"
        },
        "features": [
            "Document ingestion (PDF, DOCX, TXT, MD)",
            "Semantic search with vector embeddings",
            "Question answering with context",
            "Knowledge completeness assessment",
            "Incremental indexing",
            "Large file support"
        ]
    }


@app.get("/api/v1/indexer/status")
async def get_indexer_status():
    """Get incremental indexer status."""
    return indexer.get_status()


@app.post("/api/v1/indexer/add-directory")
async def add_watch_directory(directory_path: str):
    """Add a directory to the incremental indexer."""
    indexer.add_watch_directory(directory_path)
    return {"message": f"Added watch directory: {directory_path}"}


@app.post("/api/v1/indexer/remove-directory")
async def remove_watch_directory(directory_path: str):
    """Remove a directory from the incremental indexer."""
    indexer.remove_watch_directory(directory_path)
    return {"message": f"Removed watch directory: {directory_path}"}


@app.post("/api/v1/indexer/force-reindex")
async def force_reindex(directory_path: str = None):
    """Force reindexing of files."""
    await indexer.force_reindex(directory_path)
    return {"message": "Force reindex completed"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )