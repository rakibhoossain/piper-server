"""Module for handling temporary file storage with automatic cleanup."""
import os
import time
from pathlib import Path
from datetime import datetime, timedelta
import logging
import uuid
import threading
import schedule
from typing import Optional

_LOGGER = logging.getLogger(__name__)

class FileStorage:
    """Handles temporary file storage with automatic cleanup."""
    
    def __init__(self, storage_dir: str, expiry_minutes: int = 20, base_url: str = ""):
        """Initialize the file storage.
        
        Args:
            storage_dir: Directory to store files in
            expiry_minutes: Minutes after which files are deleted
            base_url: Base URL for file access
        """
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.expiry_minutes = expiry_minutes
        self.base_url = base_url
        
        # Start the cleanup thread
        self._start_cleanup_scheduler()
    
    def save_file(self, data: bytes, extension: str = "wav") -> str:
        """Save data to a file and return its ID.
        
        Args:
            data: File data bytes
            extension: File extension (default: wav)
            
        Returns:
            str: Unique file ID
        """
        # Generate unique ID
        file_id = f"{uuid.uuid4()}.{extension}"
        file_path = self.storage_dir / file_id
        
        # Save file
        with open(file_path, "wb") as f:
            f.write(data)
        
        _LOGGER.debug(f"Saved file: {file_id}")
        return file_id
    
    def get_file_path(self, file_id: str) -> Optional[Path]:
        """Get the file path for a file ID.
        
        Args:
            file_id: File ID
            
        Returns:
            Path: Path to the file or None if not found
        """
        file_path = self.storage_dir / file_id
        if file_path.exists():
            return file_path
        return None
    
    def get_file_url(self, file_id: str) -> str:
        """Get the URL for a file ID.
        
        Args:
            file_id: File ID
            
        Returns:
            str: URL to access the file
        """
        return f"{self.base_url}/file/{file_id}"
    
    def delete_file(self, file_id: str) -> bool:
        """Delete a file.
        
        Args:
            file_id: File ID
            
        Returns:
            bool: True if deleted, False otherwise
        """
        file_path = self.storage_dir / file_id
        if file_path.exists():
            os.remove(file_path)
            _LOGGER.debug(f"Deleted file: {file_id}")
            return True
        return False
    
    def cleanup_old_files(self) -> int:
        """Delete files older than expiry_minutes.
        
        Returns:
            int: Number of files deleted
        """
        cutoff_time = time.time() - (self.expiry_minutes * 60)
        count = 0
        
        for file_path in self.storage_dir.iterdir():
            if file_path.is_file():
                mtime = file_path.stat().st_mtime
                if mtime < cutoff_time:
                    try:
                        os.remove(file_path)
                        count += 1
                    except Exception as e:
                        _LOGGER.error(f"Error deleting {file_path}: {e}")
        
        if count > 0:
            _LOGGER.info(f"Cleaned up {count} old files")
        
        return count
    
    def _start_cleanup_scheduler(self):
        """Start the cleanup scheduler in a separate thread."""
        def run_scheduler():
            _LOGGER.info("Started file cleanup scheduler")
            schedule.every(1).minutes.do(self.cleanup_old_files)
            
            while True:
                schedule.run_pending()
                time.sleep(10)
        
        thread = threading.Thread(target=run_scheduler, daemon=True)
        thread.start()
