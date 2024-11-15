"""Path management utilities"""

import os
import tempfile
import shutil
import stat
import logging
import contextlib
import time

logger = logging.getLogger("VideoArchiver")

@contextlib.contextmanager
def temp_path_context():
    """Context manager for temporary path creation and cleanup"""
    temp_dir = None
    try:
        # Create temp directory with proper permissions
        temp_dir = tempfile.mkdtemp(prefix="videoarchiver_")
        logger.debug(f"Created temporary directory: {temp_dir}")
        
        # Ensure directory has rwx permissions for user only
        os.chmod(temp_dir, stat.S_IRWXU)
        
        # Verify directory exists and is writable
        if not os.path.exists(temp_dir):
            raise OSError(f"Failed to create temporary directory: {temp_dir}")
        if not os.access(temp_dir, os.W_OK):
            raise OSError(f"Temporary directory is not writable: {temp_dir}")
            
        yield temp_dir
        
    except Exception as e:
        logger.error(f"Error in temp_path_context: {str(e)}")
        raise
        
    finally:
        if temp_dir and os.path.exists(temp_dir):
            try:
                # Ensure all files are deletable with retries
                max_retries = 3
                for attempt in range(max_retries):
                    try:
                        # Set permissions recursively
                        for root, dirs, files in os.walk(temp_dir):
                            for d in dirs:
                                try:
                                    dir_path = os.path.join(root, d)
                                    os.chmod(dir_path, stat.S_IRWXU)
                                except OSError as e:
                                    logger.warning(f"Failed to set permissions on directory {dir_path}: {e}")
                            for f in files:
                                try:
                                    file_path = os.path.join(root, f)
                                    os.chmod(file_path, stat.S_IRWXU)
                                except OSError as e:
                                    logger.warning(f"Failed to set permissions on file {file_path}: {e}")
                        
                        # Try to remove the directory
                        shutil.rmtree(temp_dir, ignore_errors=True)
                        
                        # Verify directory is gone
                        if not os.path.exists(temp_dir):
                            logger.debug(f"Successfully cleaned up temporary directory: {temp_dir}")
                            break
                            
                        if attempt < max_retries - 1:
                            time.sleep(1)  # Wait before retry
                            
                    except Exception as e:
                        if attempt == max_retries - 1:
                            logger.error(f"Failed to clean up temporary directory {temp_dir} after {max_retries} attempts: {e}")
                        elif attempt < max_retries - 1:
                            time.sleep(1)  # Wait before retry
                            continue
                            
            except Exception as e:
                logger.error(f"Error during temp directory cleanup: {str(e)}")
