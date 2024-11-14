"""Path management utilities"""

import os
import tempfile
import shutil
import stat
import logging
import contextlib

logger = logging.getLogger("VideoArchiver")

@contextlib.contextmanager
def temp_path_context():
    """Context manager for temporary path creation and cleanup"""
    temp_dir = tempfile.mkdtemp(prefix="videoarchiver_")
    try:
        # Ensure proper permissions
        os.chmod(temp_dir, stat.S_IRWXU)
        yield temp_dir
    finally:
        try:
            # Ensure all files are deletable
            for root, dirs, files in os.walk(temp_dir):
                for d in dirs:
                    try:
                        os.chmod(os.path.join(root, d), stat.S_IRWXU)
                    except OSError:
                        pass
                for f in files:
                    try:
                        os.chmod(os.path.join(root, f), stat.S_IRWXU)
                    except OSError:
                        pass
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception as e:
            logger.error(f"Error cleaning up temp directory {temp_dir}: {e}")
