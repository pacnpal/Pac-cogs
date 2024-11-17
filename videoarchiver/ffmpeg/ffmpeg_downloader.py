"""FFmpeg binary downloader and manager"""

import os
import logging
import shutil
import requests
import tarfile
import zipfile
import subprocess
import tempfile
import platform
import hashlib
from pathlib import Path
from contextlib import contextmanager
from typing import Optional, Dict, List
import time
import lzma

try:
    # Try relative imports first
    from .exceptions import DownloadError
except ImportError:
    # Fall back to absolute imports if relative imports fail
    from videoarchiver.ffmpeg.exceptions import DownloadError

logger = logging.getLogger("VideoArchiver")


@contextmanager
def temp_path_context():
    """Context manager for temporary path creation and cleanup"""
    temp_dir = tempfile.mkdtemp(prefix="ffmpeg_")
    try:
        os.chmod(temp_dir, 0o777)
        yield temp_dir
    finally:
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception as e:
            logger.error(f"Error cleaning up temp directory {temp_dir}: {e}")


[REST OF FILE CONTENT REMAINS THE SAME]
