"""Path management utilities"""

import asyncio
import os
import tempfile
import shutil
import stat
import logging
import contextlib
import time
from typing import List, Optional, AsyncGenerator
from pathlib import Path

from utils.exceptions import FileCleanupError
from utils.permission_manager import PermissionManager

logger = logging.getLogger("PathManager")

class TempDirectoryManager:
    """Manages temporary directory creation and cleanup"""

    def __init__(self):
        self.permission_manager = PermissionManager()
        self.max_retries = 3
        self.retry_delay = 1

    async def create_temp_dir(self, prefix: str = "videoarchiver_") -> str:
        """Create a temporary directory with proper permissions
        
        Args:
            prefix: Prefix for temporary directory name
            
        Returns:
            str: Path to temporary directory
            
        Raises:
            FileCleanupError: If directory creation fails
        """
        try:
            # Create temp directory
            temp_dir = tempfile.mkdtemp(prefix=prefix)
            logger.debug(f"Created temporary directory: {temp_dir}")
            
            # Set proper permissions
            await self.permission_manager.set_permissions(
                temp_dir,
                stat.S_IRWXU,  # rwx for user only
                recursive=False
            )
            
            # Verify directory
            if not await self._verify_directory(temp_dir):
                raise FileCleanupError(f"Failed to verify temporary directory: {temp_dir}")
                
            return temp_dir
            
        except Exception as e:
            logger.error(f"Error creating temporary directory: {e}")
            raise FileCleanupError(f"Failed to create temporary directory: {str(e)}")

    async def cleanup_temp_dir(self, temp_dir: str) -> List[str]:
        """Clean up a temporary directory
        
        Args:
            temp_dir: Path to temporary directory
            
        Returns:
            List[str]: List of any cleanup errors
        """
        if not temp_dir or not os.path.exists(temp_dir):
            return []

        cleanup_errors = []
        
        try:
            # Set permissions recursively
            await self._prepare_for_cleanup(temp_dir, cleanup_errors)
            
            # Attempt cleanup with retries
            for attempt in range(self.max_retries):
                try:
                    # Remove directory
                    shutil.rmtree(temp_dir, ignore_errors=True)
                    
                    # Verify removal
                    if not os.path.exists(temp_dir):
                        logger.debug(f"Successfully cleaned up temporary directory: {temp_dir}")
                        break
                        
                    if attempt < self.max_retries - 1:
                        await self._retry_delay()
                        
                except Exception as e:
                    if attempt == self.max_retries - 1:
                        cleanup_errors.append(
                            f"Failed to clean up temporary directory {temp_dir} "
                            f"after {self.max_retries} attempts: {e}"
                        )
                    elif attempt < self.max_retries - 1:
                        await self._retry_delay()
                        continue
                        
        except Exception as e:
            cleanup_errors.append(f"Error during temp directory cleanup: {str(e)}")
            
        return cleanup_errors

    async def _prepare_for_cleanup(
        self,
        temp_dir: str,
        cleanup_errors: List[str]
    ) -> None:
        """Prepare directory for cleanup by setting permissions"""
        for root, dirs, files in os.walk(temp_dir):
            # Set directory permissions
            for d in dirs:
                try:
                    dir_path = os.path.join(root, d)
                    await self.permission_manager.set_permissions(
                        dir_path,
                        stat.S_IRWXU
                    )
                except Exception as e:
                    cleanup_errors.append(
                        f"Failed to set permissions on directory {dir_path}: {e}"
                    )
            
            # Set file permissions
            for f in files:
                try:
                    file_path = os.path.join(root, f)
                    await self.permission_manager.set_permissions(
                        file_path,
                        stat.S_IRWXU
                    )
                except Exception as e:
                    cleanup_errors.append(
                        f"Failed to set permissions on file {file_path}: {e}"
                    )

    async def _verify_directory(self, directory: str) -> bool:
        """Verify a directory exists and is writable"""
        if not os.path.exists(directory):
            return False
        return await self.permission_manager.check_permissions(
            directory,
            require_writable=True,
            require_readable=True,
            require_executable=True
        )

    async def _retry_delay(self) -> None:
        """Sleep between retry attempts"""
        await asyncio.sleep(self.retry_delay)

class PathManager:
    """Manages path operations and validation"""

    def __init__(self):
        self.temp_dir_manager = TempDirectoryManager()

    @contextlib.asynccontextmanager
    async def temp_path_context(
        self,
        prefix: str = "videoarchiver_"
    ) -> AsyncGenerator[str, None]:
        """Async context manager for temporary path creation and cleanup
        
        Args:
            prefix: Prefix for temporary directory name
            
        Yields:
            str: Path to temporary directory
            
        Raises:
            FileCleanupError: If directory creation or cleanup fails
        """
        temp_dir = None
        try:
            # Create temporary directory
            temp_dir = await self.temp_dir_manager.create_temp_dir(prefix)
            yield temp_dir
            
        except FileCleanupError:
            raise
        except Exception as e:
            logger.error(f"Error in temp_path_context: {str(e)}")
            raise FileCleanupError(f"Temporary directory error: {str(e)}")
            
        finally:
            if temp_dir:
                # Clean up directory
                cleanup_errors = await self.temp_dir_manager.cleanup_temp_dir(temp_dir)
                if cleanup_errors:
                    error_msg = "\n".join(cleanup_errors)
                    logger.error(error_msg)
                    # Don't raise here as we're in finally block

    async def ensure_directory(self, directory: str) -> None:
        """Ensure a directory exists with proper permissions
        
        Args:
            directory: Path to ensure exists
            
        Raises:
            FileCleanupError: If directory cannot be created or accessed
        """
        try:
            path = Path(directory)
            path.mkdir(parents=True, exist_ok=True)
            
            # Set proper permissions
            await self.temp_dir_manager.permission_manager.set_permissions(
                directory,
                stat.S_IRWXU
            )
            
            # Verify directory
            if not await self.temp_dir_manager._verify_directory(directory):
                raise FileCleanupError(f"Failed to verify directory: {directory}")
                
        except Exception as e:
            logger.error(f"Error ensuring directory {directory}: {e}")
            raise FileCleanupError(f"Failed to ensure directory: {str(e)}")
