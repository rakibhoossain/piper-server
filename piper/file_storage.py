"""Module for handling temporary file storage with automatic cleanup."""
import os
import time
from pathlib import Path
from datetime import datetime, timedelta
import logging
import uuid
import threading
try:
    import schedule
except ImportError:
    # If schedule is not installed, implement a simple scheduler
    class SimpleScheduler:
        def __init__(self):
            self.tasks = []
            
        def every(self, interval):
            return TaskScheduler(interval, self)
            
        def run_pending(self):
            current_time = time.time()
            for task in self.tasks:
                if task['last_run'] + task['interval'] <= current_time:
                    task['job']() 
                    task['last_run'] = current_time
    
    class TaskScheduler:
        def __init__(self, interval, scheduler):
            self.interval = interval
            self.scheduler = scheduler
            
        def minutes(self):
            self.interval_seconds = self.interval * 60
            return self
            
        def do(self, job):
            self.scheduler.tasks.append({
                'interval': self.interval_seconds,
                'job': job,
                'last_run': time.time()
            })
            return job
    
    schedule = SimpleScheduler()
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
        
        # Ensure the storage directory exists
        if not self.storage_dir.exists():
            self.storage_dir.mkdir(parents=True, exist_ok=True)
            return 0
        
        # Go through all files in the directory
        for file_path in self.storage_dir.iterdir():
            if file_path.is_file():
                try:
                    mtime = file_path.stat().st_mtime
                    file_age_minutes = (time.time() - mtime) / 60
                    
                    # Delete files older than expiry time
                    if mtime < cutoff_time:
                        os.remove(file_path)
                        count += 1
                        print(f"Deleted old file: {file_path.name} (age: {file_age_minutes:.1f} minutes)")
                except Exception as e:
                    _LOGGER.error(f"Error processing {file_path}: {e}")
        
        if count > 0:
            _LOGGER.info(f"Cleaned up {count} old files")
            print(f"Cleaned up {count} files older than {self.expiry_minutes} minutes")
        
        return count
    
    def _start_cleanup_scheduler(self):
        """Start the cleanup scheduler in a separate thread."""
        def run_scheduler():
            _LOGGER.info("Started file cleanup scheduler")
            # Run cleanup right away to make sure it works
            self.cleanup_old_files()
            
            # Schedule periodic cleanup (every 1 minute)
            schedule.every(1).minutes.do(self.cleanup_old_files)
            
            while True:
                try:
                    schedule.run_pending()
                except Exception as e:
                    _LOGGER.error(f"Error in cleanup scheduler: {e}")
                time.sleep(10)
        
        # Start the scheduler in a daemon thread so it doesn't block program exit
        thread = threading.Thread(target=run_scheduler, daemon=True)
        thread.start()
        _LOGGER.info(f"File cleanup scheduler started with {self.expiry_minutes} minute expiry time")
