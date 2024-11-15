"""File operation utilities"""

import os
import stat
import asyncio
import logging
from pathlib import Path
from typing import Optional

from .exceptions import FileCleanupError

logger = logging.getLogger("VideoArchiver")

async def secure_delete_file(file_path: str, max_size: int = 100 * 1024 * 1024) -> bool:
    """Delete a file securely
    
    Args:
        file_path: Path to the file to delete
        max_size: Maximum file size in bytes to attempt secure deletion (default: 100MB)
        
    Returns:
        bool: True if file was successfully deleted, False otherwise
        
    Raises:
        FileCleanupError: If file deletion fails after all attempts
    """
    if not os.path.exists(file_path):
        return True

    try:
        # Get file size
        try:
            file_size = os.path.getsize(file_path)
        except OSError as e:
            logger.warning(f"Could not get size of {file_path}: {e}")
            file_size = 0

        # For large files, skip secure deletion and just remove
        if file_size > max_size:
            logger.debug(f"File {file_path} exceeds max size for secure deletion, performing direct removal")
            try:
                os.remove(file_path)
                return True
            except OSError as e:
                logger.error(f"Failed to remove large file {file_path}: {e}")
                return False

        # Ensure file is writable
        try:
            current_mode = os.stat(file_path).st_mode
            os.chmod(file_path, current_mode | stat.S_IWRITE)
        except OSError as e:
            logger.warning(f"Could not modify permissions of {file_path}: {e}")
            raise FileCleanupError(f"Permission error: {str(e)}")

        # Zero out file content in chunks to avoid memory issues
        if file_size > 0:
            try:
                chunk_size = min(1024 * 1024, file_size)  # 1MB chunks or file size if smaller
                with open(file_path, "wb") as f:
                    for offset in range(0, file_size, chunk_size):
                        write_size = min(chunk_size, file_size - offset)
                        f.write(b'\0' * write_size)
                        # Allow other tasks to run
                        await asyncio.sleep(0)
                    f.flush()
                    os.fsync(f.fileno())
            except OSError as e:
                logger.warning(f"Error zeroing file {file_path}: {e}")

        # Delete the file
        try:
            Path(file_path).unlink(missing_ok=True)
            return True
        except OSError as e:
            logger.error(f"Failed to delete file {file_path}: {e}")
            return False

    except Exception as e:
        logger.error(f"Error during deletion of {file_path}: {e}")
        # Last resort: try force delete
        try:
            if os.path.exists(file_path):
                os.chmod(file_path, stat.S_IWRITE | stat.S_IREAD)
                Path(file_path).unlink(missing_ok=True)
        except Exception as e2:
            logger.error(f"Force delete failed for {file_path}: {e2}")
            raise FileCleanupError(f"Force delete failed: {str(e2)}")
        return not os.path.exists(file_path)

async def cleanup_downloads(download_path: str) -> None:
    """Clean up the downloads directory
    
    Args:
        download_path: Path to the downloads directory to clean
        
    Raises:
        FileCleanupError: If cleanup fails
    """
    try:
        if not os.path.exists(download_path):
            return

        errors = []
        # Delete all files in the directory
        for entry in os.scandir(download_path):
            try:
                path = entry.path
                if entry.is_file():
                    if not await secure_delete_file(path):
                        errors.append(f"Failed to delete file: {path}")
                elif entry.is_dir():
                    await asyncio.to_thread(lambda: os.rmdir(path) if not os.listdir(path) else None)
            except Exception as e:
                errors.append(f"Error processing {entry.path}: {str(e)}")
                continue

        # Clean up empty subdirectories
        for root, dirs, files in os.walk(download_path, topdown=False):
            for name in dirs:
                try:
                    dir_path = os.path.join(root, name)
                    if not os.listdir(dir_path):  # Check if directory is empty
                        await asyncio.to_thread(os.rmdir, dir_path)
                except Exception as e:
                    errors.append(f"Error removing directory {name}: {str(e)}")

        if errors:
            raise FileCleanupError("\n".join(errors))

    except FileCleanupError:
        raise
    except Exception as e:
        logger.error(f"Error during cleanup of {download_path}: {e}")
        raise FileCleanupError(f"Cleanup failed: {str(e)}")
