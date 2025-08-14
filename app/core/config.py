from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql+asyncpg://user:password@localhost:5432/knowledge_base"
    redis_url: str = "redis://localhost:6379"
    
    # OpenAI (deprecated - use Ollama instead)
    openai_api_key: Optional[str] = None
    
    # Ollama
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2:1b"  # Small, fast model for reasoning
    
    # Vector Database
    chroma_persist_directory: str = "./chroma_db"
    
    # Application
    secret_key: str = "your-secret-key-here"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    
    # Embedding Model
    embedding_model: str = "all-MiniLM-L6-v2"
    embedding_dimension: int = 384
    
    # File Processing
    max_file_size_mb: int = 100
    chunk_size: int = 1000
    chunk_overlap: int = 200
    
    # Search
    default_search_limit: int = 10
    similarity_threshold: float = 0.3
    
    class Config:
        env_file = ".env"


@lru_cache()
def get_settings() -> Settings:
    return Settings()