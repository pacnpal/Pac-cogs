"""File operation utilities"""

import os
import stat
import time
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

from .exceptions import FileCleanupError

logger = logging.getLogger("VideoArchiver")

def secure_delete_file(file_path: str, passes: int = 3, timeout: int = 30) -> bool:
    """Securely delete a file by overwriting it multiple times before removal
    
    Args:
        file_path: Path to the file to delete
        passes: Number of overwrite passes (default: 3)
        timeout: Maximum time in seconds to attempt deletion (default: 30)
        
    Returns:
        bool: True if file was successfully deleted, False otherwise
        
    Raises:
        FileCleanupError: If file deletion fails after all attempts
    """
    if not os.path.exists(file_path):
        return True

    start_time = datetime.now()
    try:
        # Get file size before starting
        try:
            file_size = os.path.getsize(file_path)
        except OSError as e:
            file_size = 0
            logger.warning(f"Could not get size of {file_path}: {e}")

        # Ensure file is writable
        try:
            current_mode = os.stat(file_path).st_mode
            os.chmod(file_path, current_mode | stat.S_IWRITE)
        except OSError as e:
            logger.warning(f"Could not modify permissions of {file_path}: {e}")
            raise FileCleanupError(f"Permission error: {str(e)}")

        # Overwrite file content
        if file_size > 0:
            for pass_num in range(passes):
                try:
                    with open(file_path, "wb") as f:
                        # Write random data
                        f.write(os.urandom(file_size))
                        # Ensure data is written to disk
                        f.flush()
                        os.fsync(f.fileno())
                except OSError as e:
                    logger.warning(f"Error during pass {pass_num + 1} of overwriting {file_path}: {e}")
                    continue

        # Try multiple deletion methods
        deletion_methods = [
            lambda p: os.remove(p),
            lambda p: os.unlink(p),
            lambda p: Path(p).unlink(missing_ok=True),
            lambda p: shutil.rmtree(p, ignore_errors=True) if os.path.isdir(p) else os.remove(p)
        ]

        for method in deletion_methods:
            try:
                if os.path.exists(file_path):
                    method(file_path)
                if not os.path.exists(file_path):
                    logger.debug(f"Successfully deleted {file_path}")
                    return True
            except OSError as e:
                logger.debug(f"Deletion method failed for {file_path}: {e}")
                continue

        # If file still exists, check timeout
        while os.path.exists(file_path):
            if (datetime.now() - start_time).total_seconds() > timeout:
                logger.error(f"Timeout while trying to delete {file_path}")
                raise FileCleanupError(f"Deletion timeout for {file_path}")
            time.sleep(0.1)

        return True

    except FileCleanupError:
        raise
    except Exception as e:
        logger.error(f"Error during secure deletion of {file_path}: {e}")
        # Last resort: try force delete
        try:
            if os.path.exists(file_path):
                os.chmod(file_path, stat.S_IWRITE | stat.S_IREAD)
                Path(file_path).unlink(missing_ok=True)
        except Exception as e2:
            logger.error(f"Force delete failed for {file_path}: {e2}")
            raise FileCleanupError(f"Force delete failed: {str(e2)}")
        return not os.path.exists(file_path)

def cleanup_downloads(download_path: str) -> None:
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
                    if not secure_delete_file(path):
                        errors.append(f"Failed to delete file: {path}")
                elif entry.is_dir():
                    shutil.rmtree(path, ignore_errors=True)
            except Exception as e:
                errors.append(f"Error processing {entry.path}: {str(e)}")
                continue

        # Clean up empty subdirectories
        for root, dirs, files in os.walk(download_path, topdown=False):
            for name in dirs:
                try:
                    dir_path = os.path.join(root, name)
                    if not os.listdir(dir_path):  # Check if directory is empty
                        os.rmdir(dir_path)
                except Exception as e:
                    errors.append(f"Error removing directory {name}: {str(e)}")

        if errors:
            raise FileCleanupError("\n".join(errors))

    except FileCleanupError:
        raise
    except Exception as e:
        logger.error(f"Error during cleanup of {download_path}: {e}")
        raise FileCleanupError(f"Cleanup failed: {str(e)}")
