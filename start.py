#!/usr/bin/env python3
"""
Startup script for AI Knowledge Base
Handles initialization and dependency checks
"""

import asyncio
import os
import sys
from pathlib import Path

import uvicorn
from loguru import logger


def check_dependencies():
    """Check if all required dependencies are available."""
    required_packages = [
        "fastapi", "uvicorn", "sqlalchemy", "chromadb", 
        "sentence_transformers", "PyPDF2", "python-docx"
    ]
    
    missing = []
    for package in required_packages:
        try:
            __import__(package.replace("-", "_"))
        except ImportError:
            missing.append(package)
    
    if missing:
        logger.error(f"Missing required packages: {', '.join(missing)}")
        logger.info("Install with: pip install poetry && poetry install")
        return False
    
    return True


def setup_directories():
    """Create necessary directories."""
    directories = [
        "uploads",
        "documents", 
        "chroma_db",
        "logs"
    ]
    
    for directory in directories:
        Path(directory).mkdir(exist_ok=True)
        logger.info(f"Created directory: {directory}")


def check_env_file():
    """Check if .env file exists and warn if not."""
    if not os.path.exists(".env"):
        logger.warning(".env file not found!")
        logger.info("Copy .env.example to .env and configure your settings")
        logger.info("cp .env.example .env")
        return False
    return True


async def check_database():
    """Check database connection."""
    try:
        from app.core.database import engine
        async with engine.connect() as conn:
            await conn.execute("SELECT 1")
        logger.info("Database connection successful")
        return True
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        logger.info("Make sure PostgreSQL is running and DATABASE_URL is correct")
        return False


def main():
    """Main startup function."""
    logger.info("🚀 Starting AI Knowledge Base...")
    
    # Check dependencies
    if not check_dependencies():
        sys.exit(1)
    
    # Setup directories
    setup_directories()
    
    # Check environment
    if not check_env_file():
        logger.warning("Continuing with default settings...")
    
    # Check database connection
    try:
        if not asyncio.run(check_database()):
            logger.error("Database check failed")
            sys.exit(1)
    except Exception as e:
        logger.error(f"Error checking database: {e}")
        sys.exit(1)
    
    # Start the application
    logger.info("✅ All checks passed. Starting FastAPI server...")
    logger.info("📚 API Documentation: http://localhost:8000/docs")
    logger.info("🔍 Health Check: http://localhost:8000/api/v1/health")
    
    try:
        uvicorn.run(
            "app.main:app",
            host="0.0.0.0",
            port=8000,
            reload=True,
            log_level="info",
            access_log=True
        )
    except KeyboardInterrupt:
        logger.info("👋 Shutting down gracefully...")
    except Exception as e:
        logger.error(f"Error starting server: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()