"""File operation utilities"""

import logging
from pathlib import Path
from typing import List, Tuple, Optional

from .exceptions import FileCleanupError
from .file_deletion import SecureFileDeleter
from .directory_manager import DirectoryManager
from .permission_manager import PermissionManager

logger = logging.getLogger("VideoArchiver")

class FileOperations:
    """Manages file and directory operations"""

    def __init__(self):
        """Initialize file operation managers"""
        self.file_deleter = SecureFileDeleter()
        self.directory_manager = DirectoryManager()
        self.permission_manager = PermissionManager()

    async def secure_delete_file(
        self,
        file_path: str,
        max_size: Optional[int] = None
    ) -> bool:
        """Delete a file securely
        
        Args:
            file_path: Path to the file to delete
            max_size: Optional maximum file size for secure deletion
            
        Returns:
            bool: True if file was successfully deleted
            
        Raises:
            FileCleanupError: If file deletion fails
        """
        try:
            # Ensure file is writable before deletion
            await self.permission_manager.ensure_writable(file_path)
            
            # Perform secure deletion
            if max_size:
                self.file_deleter.max_size = max_size
            return await self.file_deleter.delete_file(file_path)

        except Exception as e:
            logger.error(f"Error during secure file deletion: {e}")
            raise FileCleanupError(f"Secure deletion failed: {str(e)}")

    async def cleanup_downloads(
        self,
        download_path: str,
        recursive: bool = True,
        delete_empty: bool = True
    ) -> None:
        """Clean up the downloads directory
        
        Args:
            download_path: Path to the downloads directory
            recursive: Whether to clean subdirectories
            delete_empty: Whether to delete empty directories
            
        Raises:
            FileCleanupError: If cleanup fails
        """
        try:
            # Ensure we have necessary permissions
            await self.permission_manager.ensure_writable(
                download_path,
                recursive=recursive
            )

            # Perform cleanup
            deleted_count, errors = await self.directory_manager.cleanup_directory(
                download_path,
                recursive=recursive,
                delete_empty=delete_empty
            )

            # Log results
            if errors:
                error_msg = "\n".join(errors)
                logger.error(f"Cleanup completed with errors:\n{error_msg}")
                raise FileCleanupError(f"Cleanup completed with {len(errors)} errors")
            else:
                logger.info(f"Successfully cleaned up {deleted_count} files")

        except Exception as e:
            logger.error(f"Error during downloads cleanup: {e}")
            raise FileCleanupError(f"Downloads cleanup failed: {str(e)}")

    async def ensure_directory(self, directory_path: str) -> None:
        """Ensure a directory exists with proper permissions
        
        Args:
            directory_path: Path to the directory
            
        Raises:
            FileCleanupError: If directory cannot be created or accessed
        """
        try:
            # Create directory if needed
            await self.directory_manager.ensure_directory(directory_path)
            
            # Set proper permissions
            await self.permission_manager.fix_permissions(directory_path)
            
            # Verify it's writable
            if not await self.permission_manager.check_permissions(
                directory_path,
                require_writable=True,
                require_readable=True,
                require_executable=True
            ):
                raise FileCleanupError(f"Directory {directory_path} has incorrect permissions")

        except Exception as e:
            logger.error(f"Error ensuring directory: {e}")
            raise FileCleanupError(f"Failed to ensure directory: {str(e)}")

    async def get_directory_info(
        self,
        directory_path: str
    ) -> Tuple[int, List[str]]:
        """Get directory size and any permission issues
        
        Args:
            directory_path: Path to the directory
            
        Returns:
            Tuple[int, List[str]]: (Total size in bytes, List of permission issues)
        """
        try:
            # Get directory size
            total_size = await self.directory_manager.get_directory_size(directory_path)
            
            # Check permissions
            permission_issues = await self.permission_manager.fix_permissions(
                directory_path,
                recursive=True
            )
            
            return total_size, permission_issues

        except Exception as e:
            logger.error(f"Error getting directory info: {e}")
            return 0, [f"Error: {str(e)}"]
