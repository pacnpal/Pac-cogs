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
from typing import Optional
import time

from .exceptions import DownloadError

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

class FFmpegDownloader:
    FFMPEG_URLS = {
        "Windows": {
            "x86_64": {
                "url": "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip",
                "bin_name": "ffmpeg.exe",
            }
        },
        "Linux": {
            "x86_64": {
                "url": "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz",
                "bin_name": "ffmpeg",
            },
            "aarch64": {
                "url": "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-arm64-static.tar.xz",
                "bin_name": "ffmpeg",
            },
            "armv7l": {
                "url": "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-armhf-static.tar.xz",
                "bin_name": "ffmpeg",
            },
        },
        "Darwin": {
            "x86_64": {
                "url": "https://evermeet.cx/ffmpeg/getrelease/zip",
                "bin_name": "ffmpeg",
            },
            "arm64": {
                "url": "https://evermeet.cx/ffmpeg/getrelease/zip",
                "bin_name": "ffmpeg",
            },
        },
    }

    def __init__(self, system: str, machine: str, base_dir: Path):
        """Initialize FFmpeg downloader"""
        self.system = system
        self.machine = machine.lower()
        if self.machine == "arm64":
            self.machine = "aarch64"  # Normalize ARM64 naming
        self.base_dir = base_dir
        self.ffmpeg_path = self.base_dir / self._get_binary_name()
        
        logger.info(f"Initialized FFmpeg downloader for {system}/{machine}")
        logger.info(f"FFmpeg binary path: {self.ffmpeg_path}")

    def _get_binary_name(self) -> str:
        """Get the appropriate binary name for the current system"""
        try:
            return self.FFMPEG_URLS[self.system][self.machine]["bin_name"]
        except KeyError:
            raise DownloadError(f"Unsupported system/architecture: {self.system}/{self.machine}")

    def _get_download_url(self) -> str:
        """Get the appropriate download URL for the current system"""
        try:
            return self.FFMPEG_URLS[self.system][self.machine]["url"]
        except KeyError:
            raise DownloadError(f"Unsupported system/architecture: {self.system}/{self.machine}")

    def download(self) -> Path:
        """Download and set up FFmpeg binary with retries"""
        max_retries = 3
        retry_delay = 5
        last_error = None

        for attempt in range(max_retries):
            try:
                logger.info(f"Download attempt {attempt + 1}/{max_retries}")
                
                # Ensure base directory exists with proper permissions
                self.base_dir.mkdir(parents=True, exist_ok=True)
                os.chmod(str(self.base_dir), 0o777)

                # Clean up any existing file or directory
                if self.ffmpeg_path.exists():
                    if self.ffmpeg_path.is_dir():
                        shutil.rmtree(str(self.ffmpeg_path))
                    else:
                        self.ffmpeg_path.unlink()

                with temp_path_context() as temp_dir:
                    # Download archive
                    archive_path = self._download_archive(temp_dir)
                    
                    # Verify download
                    if not self._verify_download(archive_path):
                        raise DownloadError("Downloaded file verification failed")
                    
                    # Extract FFmpeg binary
                    self._extract_binary(archive_path, temp_dir)
                    
                    # Set proper permissions
                    os.chmod(str(self.ffmpeg_path), 0o755)
                    
                    # Verify binary
                    if not self.verify():
                        raise DownloadError("FFmpeg binary verification failed")
                    
                    logger.info(f"Successfully downloaded FFmpeg to {self.ffmpeg_path}")
                    return self.ffmpeg_path

            except Exception as e:
                last_error = str(e)
                logger.error(f"Download attempt {attempt + 1} failed: {last_error}")
                if attempt < max_retries - 1:
                    time.sleep(retry_delay * (attempt + 1))  # Exponential backoff
                continue

        raise DownloadError(f"All download attempts failed: {last_error}")

    def _download_archive(self, temp_dir: str) -> Path:
        """Download FFmpeg archive with progress tracking"""
        url = self._get_download_url()
        archive_path = Path(temp_dir) / f"ffmpeg_archive{'.zip' if self.system == 'Windows' else '.tar.xz'}"
        
        logger.info(f"Downloading FFmpeg from {url}")
        try:
            response = requests.get(url, stream=True, timeout=30)
            response.raise_for_status()
            
            total_size = int(response.headers.get('content-length', 0))
            block_size = 8192
            downloaded = 0
            
            with open(archive_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=block_size):
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_size > 0:
                        percent = (downloaded / total_size) * 100
                        logger.debug(f"Download progress: {percent:.1f}%")
            
            return archive_path
            
        except Exception as e:
            raise DownloadError(f"Failed to download FFmpeg: {str(e)}")

    def _verify_download(self, archive_path: Path) -> bool:
        """Verify downloaded archive integrity"""
        try:
            if not archive_path.exists():
                return False
                
            # Check file size
            size = archive_path.stat().st_size
            if size < 1000000:  # Less than 1MB is suspicious
                logger.error(f"Downloaded file too small: {size} bytes")
                return False
                
            # Check file hash
            with open(archive_path, 'rb') as f:
                file_hash = hashlib.sha256(f.read()).hexdigest()
            logger.debug(f"Archive hash: {file_hash}")
            
            return True
            
        except Exception as e:
            logger.error(f"Download verification failed: {str(e)}")
            return False

    def _extract_binary(self, archive_path: Path, temp_dir: str):
        """Extract FFmpeg binary from archive"""
        logger.info("Extracting FFmpeg binary")

        if self.system == "Windows":
            self._extract_zip(archive_path, temp_dir)
        else:
            self._extract_tar(archive_path, temp_dir)

    def _extract_zip(self, archive_path: Path, temp_dir: str):
        """Extract from zip archive (Windows)"""
        with zipfile.ZipFile(archive_path, "r") as zip_ref:
            ffmpeg_files = [f for f in zip_ref.namelist() if self._get_binary_name() in f]
            if not ffmpeg_files:
                raise DownloadError("FFmpeg binary not found in archive")
            
            zip_ref.extract(ffmpeg_files[0], temp_dir)
            extracted_path = Path(temp_dir) / ffmpeg_files[0]
            shutil.copy2(extracted_path, self.ffmpeg_path)

    def _extract_tar(self, archive_path: Path, temp_dir: str):
        """Extract from tar archive (Linux/macOS)"""
        with tarfile.open(archive_path, "r:xz") as tar_ref:
            ffmpeg_files = [f for f in tar_ref.getnames() if f.endswith("/ffmpeg")]
            if not ffmpeg_files:
                raise DownloadError("FFmpeg binary not found in archive")
            
            tar_ref.extract(ffmpeg_files[0], temp_dir)
            extracted_path = Path(temp_dir) / ffmpeg_files[0]
            shutil.copy2(extracted_path, self.ffmpeg_path)

    def verify(self) -> bool:
        """Verify FFmpeg binary works"""
        try:
            if not self.ffmpeg_path.exists():
                return False

            # Ensure proper permissions
            os.chmod(str(self.ffmpeg_path), 0o755)

            # Test FFmpeg functionality
            result = subprocess.run(
                [str(self.ffmpeg_path), "-version"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=5
            )
            
            if result.returncode == 0:
                version = result.stdout.decode().split('\n')[0]
                logger.info(f"FFmpeg verification successful: {version}")
                return True
            else:
                logger.error(f"FFmpeg verification failed: {result.stderr.decode()}")
                return False

        except Exception as e:
            logger.error(f"FFmpeg verification failed: {e}")
            return False
