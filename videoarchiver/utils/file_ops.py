"""File operation utilities"""

import os
import stat
import time
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("VideoArchiver")

def secure_delete_file(file_path: str, passes: int = 3, timeout: int = 30) -> bool:
    """Securely delete a file by overwriting it multiple times before removal"""
    if not os.path.exists(file_path):
        return True

    start_time = datetime.now()
    while True:
        try:
            # Ensure file is writable
            try:
                os.chmod(file_path, stat.S_IRUSR | stat.S_IWUSR)
            except OSError:
                pass

            file_size = os.path.getsize(file_path)
            for _ in range(passes):
                with open(file_path, "wb") as f:
                    f.write(os.urandom(file_size))
                    f.flush()
                    os.fsync(f.fileno())

            # Try multiple deletion methods
            try:
                os.remove(file_path)
            except OSError:
                try:
                    os.unlink(file_path)
                except OSError:
                    Path(file_path).unlink(missing_ok=True)

            # Verify file is gone
            if os.path.exists(file_path):
                # If file still exists, check timeout
                if (datetime.now() - start_time).seconds > timeout:
                    logger.error(f"Timeout while trying to delete {file_path}")
                    return False
                # Wait briefly before retry
                time.sleep(0.1)
                continue

            return True

        except Exception as e:
            logger.error(f"Error during secure delete of {file_path}: {str(e)}")
            # Last resort: try force delete
            try:
                if os.path.exists(file_path):
                    os.chmod(file_path, stat.S_IRUSR | stat.S_IWUSR)
                    Path(file_path).unlink(missing_ok=True)
            except Exception as e2:
                logger.error(f"Force delete failed: {str(e2)}")
            return not os.path.exists(file_path)

def cleanup_downloads(download_path: str) -> None:
    """Clean up the downloads directory without removing the directory itself"""
    try:
        if os.path.exists(download_path):
            # Delete all files in the directory
            for file_path in Path(download_path).glob("**/*"):
                if file_path.is_file():
                    try:
                        if not secure_delete_file(str(file_path)):
                            logger.error(f"Failed to delete file: {file_path}")
                    except Exception as e:
                        logger.error(f"Error deleting file {file_path}: {str(e)}")
            
            # Clean up empty subdirectories
            for dir_path in sorted(Path(download_path).glob("**/*"), reverse=True):
                if dir_path.is_dir():
                    try:
                        dir_path.rmdir()  # Will only remove if empty
                    except OSError:
                        pass  # Directory not empty or other error
    except Exception as e:
        logger.error(f"Error during cleanup: {str(e)}")
