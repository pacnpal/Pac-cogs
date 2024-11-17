"""Module for secure file deletion operations"""

import os
import stat
import asyncio
import logging
from pathlib import Path
from typing import Optional

from videoarchiver.utils.exceptions import FileCleanupError

logger = logging.getLogger("FileDeleter")

class SecureFileDeleter:
    """Handles secure file deletion operations"""

    def __init__(self, max_size: int = 100 * 1024 * 1024):
        """Initialize the file deleter
        
        Args:
            max_size: Maximum file size in bytes for secure deletion (default: 100MB)
        """
        self.max_size = max_size

    async def delete_file(self, file_path: str) -> bool:
        """Delete a file securely
        
        Args:
            file_path: Path to the file to delete
            
        Returns:
            bool: True if file was successfully deleted
            
        Raises:
            FileCleanupError: If file deletion fails after all attempts
        """
        if not os.path.exists(file_path):
            return True

        try:
            file_size = await self._get_file_size(file_path)

            # For large files, skip secure deletion
            if file_size > self.max_size:
                return await self._delete_large_file(file_path)

            # Perform secure deletion
            await self._ensure_writable(file_path)
            if file_size > 0:
                await self._zero_file_content(file_path, file_size)
            return await self._delete_file(file_path)

        except Exception as e:
            logger.error(f"Error during deletion of {file_path}: {e}")
            return await self._force_delete(file_path)

    async def _get_file_size(self, file_path: str) -> int:
        """Get the size of a file"""
        try:
            return os.path.getsize(file_path)
        except OSError as e:
            logger.warning(f"Could not get size of {file_path}: {e}")
            return 0

    async def _delete_large_file(self, file_path: str) -> bool:
        """Delete a large file directly"""
        try:
            logger.debug(f"File {file_path} exceeds max size for secure deletion, performing direct removal")
            os.remove(file_path)
            return True
        except OSError as e:
            logger.error(f"Failed to remove large file {file_path}: {e}")
            return False

    async def _ensure_writable(self, file_path: str) -> None:
        """Ensure a file is writable"""
        try:
            current_mode = os.stat(file_path).st_mode
            os.chmod(file_path, current_mode | stat.S_IWRITE)
        except OSError as e:
            logger.warning(f"Could not modify permissions of {file_path}: {e}")
            raise FileCleanupError(f"Permission error: {str(e)}")

    async def _zero_file_content(self, file_path: str, file_size: int) -> None:
        """Zero out file content in chunks"""
        try:
            chunk_size = min(1024 * 1024, file_size)  # 1MB chunks or file size if smaller
            with open(file_path, "wb") as f:
                for offset in range(0, file_size, chunk_size):
                    write_size = min(chunk_size, file_size - offset)
                    f.write(b'\0' * write_size)
                    await asyncio.sleep(0)  # Allow other tasks to run
                f.flush()
                os.fsync(f.fileno())
        except OSError as e:
            logger.warning(f"Error zeroing file {file_path}: {e}")
            raise

    async def _delete_file(self, file_path: str) -> bool:
        """Delete a file"""
        try:
            Path(file_path).unlink(missing_ok=True)
            return True
        except OSError as e:
            logger.error(f"Failed to delete file {file_path}: {e}")
            return False

    async def _force_delete(self, file_path: str) -> bool:
        """Force delete a file as last resort"""
        try:
            if os.path.exists(file_path):
                os.chmod(file_path, stat.S_IWRITE | stat.S_IREAD)
                Path(file_path).unlink(missing_ok=True)
        except Exception as e:
            logger.error(f"Force delete failed for {file_path}: {e}")
            raise FileCleanupError(f"Force delete failed: {str(e)}")
        return not os.path.exists(file_path)
