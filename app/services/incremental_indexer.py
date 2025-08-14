import asyncio
import hashlib
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from loguru import logger

from app.models.document import Document
from app.services.ingestion_service import IngestionService
from app.core.database import AsyncSessionLocal
from app.core.config import get_settings

settings = get_settings()


class IncrementalIndexer:
    """Handles incremental indexing of documents for efficient updates."""
    
    def __init__(self):
        self.ingestion_service = IngestionService()
        self.watch_directories: Set[str] = set()
        self.file_hashes: Dict[str, str] = {}
        self.last_scan_time: Optional[datetime] = None
        self.scan_interval = 300  # 5 minutes
    
    def add_watch_directory(self, directory_path: str):
        """Add a directory to watch for changes."""
        if os.path.exists(directory_path):
            self.watch_directories.add(os.path.abspath(directory_path))
            logger.info(f"Added watch directory: {directory_path}")
        else:
            logger.warning(f"Directory does not exist: {directory_path}")
    
    def remove_watch_directory(self, directory_path: str):
        """Remove a directory from watching."""
        abs_path = os.path.abspath(directory_path)
        self.watch_directories.discard(abs_path)
        logger.info(f"Removed watch directory: {directory_path}")
    
    async def start_watching(self):
        """Start the incremental indexing process."""
        logger.info("Starting incremental indexing service")
        
        while True:
            try:
                await self._scan_and_index()
                await asyncio.sleep(self.scan_interval)
            except Exception as e:
                logger.error(f"Error in incremental indexing: {str(e)}")
                await asyncio.sleep(self.scan_interval)
    
    async def _scan_and_index(self):
        """Scan watched directories and index new/modified files."""
        if not self.watch_directories:
            return
        
        logger.info("Scanning for file changes...")
        changes = await self._detect_changes()
        
        if changes:
            async with AsyncSessionLocal() as db:
                await self._process_changes(db, changes)
        
        self.last_scan_time = datetime.utcnow()
        logger.info(f"Scan completed. Processed {len(changes)} changes.")
    
    async def _detect_changes(self) -> List[Dict]:
        """Detect file changes in watched directories."""
        changes = []
        current_files = {}
        
        # Scan all watched directories
        for watch_dir in self.watch_directories:
            for root, _, files in os.walk(watch_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    
                    # Filter supported file types
                    if not self._is_supported_file(file_path):
                        continue
                    
                    try:
                        # Get file stats
                        stat = os.stat(file_path)
                        file_size = stat.st_size
                        modified_time = datetime.fromtimestamp(stat.st_mtime)
                        
                        # Calculate file hash
                        file_hash = await self._calculate_file_hash(file_path)
                        current_files[file_path] = file_hash
                        
                        # Check if file is new or modified
                        old_hash = self.file_hashes.get(file_path)
                        
                        if old_hash is None:
                            # New file
                            changes.append({
                                "type": "new",
                                "path": file_path,
                                "hash": file_hash,
                                "size": file_size,
                                "modified_time": modified_time
                            })
                        elif old_hash != file_hash:
                            # Modified file
                            changes.append({
                                "type": "modified",
                                "path": file_path,
                                "hash": file_hash,
                                "old_hash": old_hash,
                                "size": file_size,
                                "modified_time": modified_time
                            })
                            
                    except Exception as e:
                        logger.error(f"Error processing file {file_path}: {str(e)}")
        
        # Detect deleted files
        for old_path in self.file_hashes:
            if old_path not in current_files:
                changes.append({
                    "type": "deleted",
                    "path": old_path,
                    "hash": self.file_hashes[old_path]
                })
        
        # Update file hashes
        self.file_hashes = current_files
        
        return changes
    
    async def _process_changes(self, db: AsyncSession, changes: List[Dict]):
        """Process detected file changes."""
        for change in changes:
            try:
                if change["type"] == "new":
                    await self._process_new_file(db, change)
                elif change["type"] == "modified":
                    await self._process_modified_file(db, change)
                elif change["type"] == "deleted":
                    await self._process_deleted_file(db, change)
                    
            except Exception as e:
                logger.error(f"Error processing change {change}: {str(e)}")
    
    async def _process_new_file(self, db: AsyncSession, change: Dict):
        """Process a new file."""
        logger.info(f"Processing new file: {change['path']}")
        
        try:
            # Read file content
            with open(change["path"], "rb") as f:
                content = f.read()
            
            # Determine content type
            content_type = self._get_content_type(change["path"])
            filename = os.path.basename(change["path"])
            
            # Ingest the document
            await self.ingestion_service.ingest_document(
                db=db,
                file_content=content,
                filename=filename,
                content_type=content_type,
                metadata={
                    "source": "incremental_indexer",
                    "original_path": change["path"],
                    "indexed_at": datetime.utcnow().isoformat()
                }
            )
            
        except Exception as e:
            logger.error(f"Error processing new file {change['path']}: {str(e)}")
    
    async def _process_modified_file(self, db: AsyncSession, change: Dict):
        """Process a modified file."""
        logger.info(f"Processing modified file: {change['path']}")
        
        try:
            # Find existing document by old hash
            result = await db.execute(
                select(Document).where(
                    and_(
                        Document.content_hash == change["old_hash"],
                        Document.file_path.contains(os.path.basename(change["path"]))
                    )
                )
            )
            
            existing_doc = result.scalar_one_or_none()
            
            if existing_doc:
                # Reprocess the existing document
                await self.ingestion_service.reprocess_document(db, existing_doc.id)
            else:
                # Treat as new file if not found
                await self._process_new_file(db, change)
                
        except Exception as e:
            logger.error(f"Error processing modified file {change['path']}: {str(e)}")
    
    async def _process_deleted_file(self, db: AsyncSession, change: Dict):
        """Process a deleted file."""
        logger.info(f"Processing deleted file: {change['path']}")
        
        try:
            # Find and mark document as deleted (or actually delete)
            result = await db.execute(
                select(Document).where(Document.content_hash == change["hash"])
            )
            
            document = result.scalar_one_or_none()
            
            if document:
                # Option 1: Soft delete (mark as deleted)
                document.processing_status = "deleted"
                document.processing_error = f"Source file deleted: {change['path']}"
                
                # Option 2: Hard delete (uncomment if preferred)
                # await self._cleanup_document_completely(db, document.id)
                
                await db.commit()
                
        except Exception as e:
            logger.error(f"Error processing deleted file {change['path']}: {str(e)}")
    
    async def _calculate_file_hash(self, file_path: str) -> str:
        """Calculate SHA256 hash of a file."""
        hasher = hashlib.sha256()
        
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hasher.update(chunk)
        
        return hasher.hexdigest()
    
    def _is_supported_file(self, file_path: str) -> bool:
        """Check if file type is supported."""
        supported_extensions = {".pdf", ".docx", ".txt", ".md"}
        return Path(file_path).suffix.lower() in supported_extensions
    
    def _get_content_type(self, file_path: str) -> str:
        """Get content type based on file extension."""
        extension = Path(file_path).suffix.lower()
        
        content_types = {
            ".pdf": "application/pdf",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".txt": "text/plain",
            ".md": "text/markdown"
        }
        
        return content_types.get(extension, "application/octet-stream")
    
    async def force_reindex(self, directory_path: Optional[str] = None):
        """Force reindexing of all files in a directory or all watched directories."""
        directories = [directory_path] if directory_path else list(self.watch_directories)
        
        logger.info(f"Starting force reindex for directories: {directories}")
        
        for directory in directories:
            if not os.path.exists(directory):
                logger.warning(f"Directory does not exist: {directory}")
                continue
            
            async with AsyncSessionLocal() as db:
                for root, _, files in os.walk(directory):
                    for file in files:
                        file_path = os.path.join(root, file)
                        
                        if not self._is_supported_file(file_path):
                            continue
                        
                        try:
                            # Treat as new file for force reindex
                            file_hash = await self._calculate_file_hash(file_path)
                            stat = os.stat(file_path)
                            
                            change = {
                                "type": "new",
                                "path": file_path,
                                "hash": file_hash,
                                "size": stat.st_size,
                                "modified_time": datetime.fromtimestamp(stat.st_mtime)
                            }
                            
                            await self._process_new_file(db, change)
                            
                        except Exception as e:
                            logger.error(f"Error in force reindex for {file_path}: {str(e)}")
        
        logger.info("Force reindex completed")
    
    def get_status(self) -> Dict:
        """Get indexer status information."""
        return {
            "watch_directories": list(self.watch_directories),
            "tracked_files": len(self.file_hashes),
            "last_scan_time": self.last_scan_time.isoformat() if self.last_scan_time else None,
            "scan_interval_seconds": self.scan_interval,
            "is_active": bool(self.watch_directories)
        }