import hashlib
import os
import uuid
from typing import Dict, List, Optional, Tuple

import aiofiles
from PyPDF2 import PdfReader
from docx import Document as DocxDocument
from loguru import logger

from app.core.config import get_settings

settings = get_settings()


class DocumentProcessor:
    """Handles document parsing and text extraction."""
    
    SUPPORTED_TYPES = {
        'application/pdf': 'pdf',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'docx',
        'text/plain': 'txt',
        'text/markdown': 'md'
    }
    
    def __init__(self):
        self.chunk_size = settings.chunk_size
        self.chunk_overlap = settings.chunk_overlap
    
    async def save_uploaded_file(self, file_content: bytes, filename: str) -> Tuple[str, str]:
        """Save uploaded file and return file path and content hash."""
        content_hash = hashlib.sha256(file_content).hexdigest()
        
        # Create unique filename to avoid conflicts
        file_extension = os.path.splitext(filename)[1]
        unique_filename = f"{uuid.uuid4()}{file_extension}"
        
        # Ensure upload directory exists
        upload_dir = "uploads"
        os.makedirs(upload_dir, exist_ok=True)
        
        file_path = os.path.join(upload_dir, unique_filename)
        
        async with aiofiles.open(file_path, 'wb') as f:
            await f.write(file_content)
        
        return file_path, content_hash
    
    def extract_text_from_file(self, file_path: str, file_type: str) -> str:
        """Extract text content from various file types."""
        try:
            if file_type == 'pdf':
                return self._extract_from_pdf(file_path)
            elif file_type == 'docx':
                return self._extract_from_docx(file_path)
            elif file_type in ['txt', 'md']:
                return self._extract_from_text(file_path)
            else:
                raise ValueError(f"Unsupported file type: {file_type}")
        except Exception as e:
            logger.error(f"Error extracting text from {file_path}: {str(e)}")
            raise
    
    def _extract_from_pdf(self, file_path: str) -> str:
        """Extract text from PDF file."""
        text = ""
        with open(file_path, 'rb') as file:
            pdf_reader = PdfReader(file)
            for page in pdf_reader.pages:
                text += page.extract_text() + "\n"
        return text.strip()
    
    def _extract_from_docx(self, file_path: str) -> str:
        """Extract text from DOCX file."""
        doc = DocxDocument(file_path)
        text = []
        for paragraph in doc.paragraphs:
            if paragraph.text.strip():
                text.append(paragraph.text)
        return "\n".join(text)
    
    def _extract_from_text(self, file_path: str) -> str:
        """Extract text from plain text files."""
        with open(file_path, 'r', encoding='utf-8') as file:
            return file.read()
    
    def chunk_text(self, text: str, metadata: Optional[Dict] = None) -> List[Dict]:
        """Split text into overlapping chunks for embedding."""
        if not text.strip():
            return []
        
        chunks = []
        words = text.split()
        
        for i in range(0, len(words), self.chunk_size - self.chunk_overlap):
            chunk_words = words[i:i + self.chunk_size]
            chunk_text = " ".join(chunk_words)
            
            if chunk_text.strip():
                chunk_data = {
                    "content": chunk_text,
                    "chunk_index": len(chunks),
                    "start_char": len(" ".join(words[:i])) if i > 0 else 0,
                    "end_char": len(" ".join(words[:i + len(chunk_words)])),
                    "metadata": metadata or {}
                }
                chunks.append(chunk_data)
        
        return chunks
    
    def get_file_type_from_content_type(self, content_type: str) -> Optional[str]:
        """Get standardized file type from MIME content type."""
        return self.SUPPORTED_TYPES.get(content_type)
    
    def is_supported_file_type(self, content_type: str) -> bool:
        """Check if file type is supported."""
        return content_type in self.SUPPORTED_TYPES
    
    def calculate_content_hash(self, content: str) -> str:
        """Calculate SHA256 hash of content."""
        return hashlib.sha256(content.encode('utf-8')).hexdigest()
    
    async def process_large_file(self, file_path: str, file_type: str) -> str:
        """Process large files in chunks to handle memory efficiently."""
        max_size_mb = settings.max_file_size_mb
        file_size = os.path.getsize(file_path)
        
        if file_size > max_size_mb * 1024 * 1024:
            logger.warning(f"File {file_path} exceeds maximum size limit")
            raise ValueError(f"File size exceeds {max_size_mb}MB limit")
        
        return self.extract_text_from_file(file_path, file_type)