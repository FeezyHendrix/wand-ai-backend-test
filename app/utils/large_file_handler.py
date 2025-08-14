import asyncio
import os
import tempfile
from typing import AsyncGenerator, List, Optional
import aiofiles
from loguru import logger

from app.core.config import get_settings

settings = get_settings()


class LargeFileHandler:
    """Handles processing of large files efficiently."""
    
    def __init__(self):
        self.chunk_size_bytes = 1024 * 1024  # 1MB chunks for reading
        self.max_memory_usage = 50 * 1024 * 1024  # 50MB max in memory
    
    async def process_large_file_stream(
        self, 
        file_path: str, 
        processor_func,
        chunk_size: Optional[int] = None
    ) -> AsyncGenerator[str, None]:
        """Process large file in streaming fashion."""
        chunk_size = chunk_size or self.chunk_size_bytes
        
        try:
            async with aiofiles.open(file_path, 'rb') as file:
                while True:
                    chunk = await file.read(chunk_size)
                    if not chunk:
                        break
                    
                    # Process chunk
                    processed_chunk = await processor_func(chunk)
                    if processed_chunk:
                        yield processed_chunk
                        
        except Exception as e:
            logger.error(f"Error processing large file {file_path}: {str(e)}")
            raise
    
    async def split_large_text_file(
        self, 
        file_path: str, 
        max_chunk_size: int = 10000
    ) -> List[str]:
        """Split large text file into manageable chunks."""
        chunks = []
        current_chunk = ""
        
        try:
            async with aiofiles.open(file_path, 'r', encoding='utf-8') as file:
                async for line in file:
                    if len(current_chunk) + len(line) > max_chunk_size:
                        if current_chunk:
                            chunks.append(current_chunk.strip())
                            current_chunk = ""
                    
                    current_chunk += line
                
                # Add the last chunk
                if current_chunk.strip():
                    chunks.append(current_chunk.strip())
            
            return chunks
            
        except Exception as e:
            logger.error(f"Error splitting large text file {file_path}: {str(e)}")
            raise
    
    async def process_pdf_in_chunks(self, file_path: str) -> List[str]:
        """Process large PDF files page by page."""
        try:
            from PyPDF2 import PdfReader
            
            text_chunks = []
            
            # Process PDF in pages to manage memory
            with open(file_path, 'rb') as file:
                pdf_reader = PdfReader(file)
                
                for page_num, page in enumerate(pdf_reader.pages):
                    try:
                        page_text = page.extract_text()
                        if page_text.strip():
                            text_chunks.append(f"[Page {page_num + 1}]\n{page_text}")
                    except Exception as e:
                        logger.warning(f"Error extracting page {page_num + 1}: {str(e)}")
                        continue
            
            return text_chunks
            
        except Exception as e:
            logger.error(f"Error processing PDF in chunks {file_path}: {str(e)}")
            raise
    
    async def create_temporary_chunks(
        self, 
        file_path: str, 
        chunk_size_mb: int = 10
    ) -> List[str]:
        """Create temporary files for processing large files in chunks."""
        chunk_size_bytes = chunk_size_mb * 1024 * 1024
        temp_files = []
        
        try:
            with open(file_path, 'rb') as source_file:
                chunk_num = 0
                
                while True:
                    chunk_data = source_file.read(chunk_size_bytes)
                    if not chunk_data:
                        break
                    
                    # Create temporary file for this chunk
                    temp_file = tempfile.NamedTemporaryFile(
                        delete=False, 
                        suffix=f"_chunk_{chunk_num}.tmp"
                    )
                    
                    temp_file.write(chunk_data)
                    temp_file.close()
                    
                    temp_files.append(temp_file.name)
                    chunk_num += 1
            
            return temp_files
            
        except Exception as e:
            logger.error(f"Error creating temporary chunks for {file_path}: {str(e)}")
            # Cleanup any created temp files
            for temp_file in temp_files:
                try:
                    os.unlink(temp_file)
                except:
                    pass
            raise
    
    async def cleanup_temp_files(self, temp_files: List[str]):
        """Clean up temporary files."""
        for temp_file in temp_files:
            try:
                if os.path.exists(temp_file):
                    os.unlink(temp_file)
            except Exception as e:
                logger.warning(f"Error cleaning up temp file {temp_file}: {str(e)}")
    
    def estimate_processing_time(self, file_size_bytes: int) -> float:
        """Estimate processing time based on file size."""
        # Simple heuristic: ~1MB per second processing
        base_rate = 1024 * 1024  # 1MB/sec
        estimated_seconds = file_size_bytes / base_rate
        
        # Add overhead for larger files
        if file_size_bytes > 100 * 1024 * 1024:  # > 100MB
            estimated_seconds *= 1.5
        
        return estimated_seconds
    
    async def validate_file_size(self, file_path: str) -> bool:
        """Validate if file size is within acceptable limits."""
        try:
            file_size = os.path.getsize(file_path)
            max_size = settings.max_file_size_mb * 1024 * 1024
            
            if file_size > max_size:
                logger.warning(f"File {file_path} exceeds size limit: {file_size} bytes")
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"Error validating file size for {file_path}: {str(e)}")
            return False
    
    async def get_file_info(self, file_path: str) -> dict:
        """Get comprehensive file information."""
        try:
            stat = os.stat(file_path)
            
            return {
                "path": file_path,
                "size_bytes": stat.st_size,
                "size_mb": round(stat.st_size / (1024 * 1024), 2),
                "created": stat.st_ctime,
                "modified": stat.st_mtime,
                "is_large_file": stat.st_size > 50 * 1024 * 1024,  # > 50MB
                "estimated_processing_time": self.estimate_processing_time(stat.st_size),
                "requires_chunking": stat.st_size > self.max_memory_usage
            }
            
        except Exception as e:
            logger.error(f"Error getting file info for {file_path}: {str(e)}")
            return {}
    
    async def monitor_memory_usage(self) -> dict:
        """Monitor current memory usage."""
        try:
            import psutil
            process = psutil.Process()
            memory_info = process.memory_info()
            
            return {
                "rss_mb": round(memory_info.rss / (1024 * 1024), 2),
                "vms_mb": round(memory_info.vms / (1024 * 1024), 2),
                "percent": process.memory_percent(),
                "available_mb": round(psutil.virtual_memory().available / (1024 * 1024), 2)
            }
            
        except ImportError:
            logger.warning("psutil not available for memory monitoring")
            return {"error": "psutil not available"}
        except Exception as e:
            logger.error(f"Error monitoring memory usage: {str(e)}")
            return {"error": str(e)}