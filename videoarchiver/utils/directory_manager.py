"""Module for directory management operations"""

import os
import logging
import asyncio
from pathlib import Path
from typing import List, Optional, Tuple

from ..utils.exceptions import FileCleanupError
from ..utils.file_deletion import SecureFileDeleter

logger = logging.getLogger("DirectoryManager")


class DirectoryManager:
    """Handles directory operations and cleanup"""

    def __init__(self):
        self.file_deleter = SecureFileDeleter()

    async def cleanup_directory(
        self, directory_path: str, recursive: bool = True, delete_empty: bool = True
    ) -> Tuple[int, List[str]]:
        """Clean up a directory by removing files and optionally empty subdirectories

        Args:
            directory_path: Path to the directory to clean
            recursive: Whether to clean subdirectories
            delete_empty: Whether to delete empty directories

        Returns:
            Tuple[int, List[str]]: (Number of files deleted, List of errors)

        Raises:
            FileCleanupError: If cleanup fails critically
        """
        if not os.path.exists(directory_path):
            return 0, []

        deleted_count = 0
        errors = []

        try:
            # Process files and directories
            deleted, errs = await self._process_directory_contents(
                directory_path, recursive, delete_empty
            )
            deleted_count += deleted
            errors.extend(errs)

            # Clean up empty directories if requested
            if delete_empty:
                dir_errs = await self._cleanup_empty_directories(directory_path)
                errors.extend(dir_errs)

            if errors:
                logger.warning(f"Cleanup completed with {len(errors)} errors")
            else:
                logger.info(f"Successfully cleaned directory: {directory_path}")

            return deleted_count, errors

        except Exception as e:
            logger.error(f"Error during cleanup of {directory_path}: {e}")
            raise FileCleanupError(f"Directory cleanup failed: {str(e)}")

    async def _process_directory_contents(
        self, directory_path: str, recursive: bool, delete_empty: bool
    ) -> Tuple[int, List[str]]:
        """Process contents of a directory"""
        deleted_count = 0
        errors = []

        try:
            for entry in os.scandir(directory_path):
                try:
                    if entry.is_file():
                        # Delete file
                        if await self.file_deleter.delete_file(entry.path):
                            deleted_count += 1
                        else:
                            errors.append(f"Failed to delete file: {entry.path}")
                    elif entry.is_dir() and recursive:
                        # Process subdirectory
                        subdir_deleted, subdir_errors = await self.cleanup_directory(
                            entry.path, recursive=True, delete_empty=delete_empty
                        )
                        deleted_count += subdir_deleted
                        errors.extend(subdir_errors)
                except Exception as e:
                    errors.append(f"Error processing {entry.path}: {str(e)}")

        except Exception as e:
            errors.append(f"Error scanning directory {directory_path}: {str(e)}")

        return deleted_count, errors

    async def _cleanup_empty_directories(self, start_path: str) -> List[str]:
        """Remove empty directories recursively"""
        errors = []

        try:
            for root, dirs, files in os.walk(start_path, topdown=False):
                for name in dirs:
                    try:
                        dir_path = os.path.join(root, name)
                        if not os.listdir(dir_path):  # Check if directory is empty
                            await self._remove_directory(dir_path)
                    except Exception as e:
                        errors.append(f"Error removing directory {name}: {str(e)}")

        except Exception as e:
            errors.append(f"Error walking directory tree: {str(e)}")

        return errors

    async def _remove_directory(self, dir_path: str) -> None:
        """Remove a directory safely"""
        try:
            await asyncio.to_thread(os.rmdir, dir_path)
        except Exception as e:
            logger.error(f"Failed to remove directory {dir_path}: {e}")
            raise

    async def ensure_directory(self, directory_path: str) -> None:
        """Ensure a directory exists and is accessible

        Args:
            directory_path: Path to the directory to ensure

        Raises:
            FileCleanupError: If directory cannot be created or accessed
        """
        try:
            path = Path(directory_path)
            path.mkdir(parents=True, exist_ok=True)

            # Verify directory is writable
            if not os.access(directory_path, os.W_OK):
                raise FileCleanupError(f"Directory {directory_path} is not writable")

        except Exception as e:
            logger.error(f"Error ensuring directory {directory_path}: {e}")
            raise FileCleanupError(f"Failed to ensure directory: {str(e)}")

    async def get_directory_size(self, directory_path: str) -> int:
        """Get total size of a directory in bytes

        Args:
            directory_path: Path to the directory

        Returns:
            int: Total size in bytes
        """
        total_size = 0
        try:
            for entry in os.scandir(directory_path):
                try:
                    if entry.is_file():
                        total_size += entry.stat().st_size
                    elif entry.is_dir():
                        total_size += await self.get_directory_size(entry.path)
                except Exception as e:
                    logger.warning(f"Error getting size for {entry.path}: {e}")
        except Exception as e:
            logger.error(f"Error calculating directory size: {e}")

        return total_size
