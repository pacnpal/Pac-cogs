"""Module for managing file and directory permissions"""

import os
import stat
import logging
from pathlib import Path
from typing import Optional, Union, List

from videoarchiver.utils.exceptions import FileCleanupError

logger = logging.getLogger("PermissionManager")

class PermissionManager:
    """Handles file and directory permission operations"""

    DEFAULT_FILE_MODE = 0o644  # rw-r--r--
    DEFAULT_DIR_MODE = 0o755   # rwxr-xr-x
    FULL_ACCESS_MODE = 0o777   # rwxrwxrwx

    def __init__(self):
        self._is_windows = os.name == 'nt'

    async def ensure_writable(
        self,
        path: Union[str, Path],
        recursive: bool = False
    ) -> None:
        """Ensure a path is writable
        
        Args:
            path: Path to make writable
            recursive: Whether to apply recursively to directories
            
        Raises:
            FileCleanupError: If permissions cannot be modified
        """
        try:
            path = Path(path)
            if not path.exists():
                return

            if path.is_file():
                await self._make_file_writable(path)
            elif path.is_dir():
                await self._make_directory_writable(path, recursive)

        except Exception as e:
            logger.error(f"Error ensuring writable permissions for {path}: {e}")
            raise FileCleanupError(f"Failed to set writable permissions: {str(e)}")

    async def _make_file_writable(self, path: Path) -> None:
        """Make a file writable"""
        try:
            current_mode = path.stat().st_mode
            if self._is_windows:
                os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
            else:
                os.chmod(path, current_mode | stat.S_IWRITE)
        except Exception as e:
            logger.error(f"Failed to make file {path} writable: {e}")
            raise

    async def _make_directory_writable(
        self,
        path: Path,
        recursive: bool
    ) -> None:
        """Make a directory writable"""
        try:
            if self._is_windows:
                os.chmod(path, stat.S_IWRITE | stat.S_IREAD | stat.S_IEXEC)
            else:
                current_mode = path.stat().st_mode
                os.chmod(path, current_mode | stat.S_IWRITE | stat.S_IEXEC)

            if recursive:
                for item in path.rglob('*'):
                    if item.is_file():
                        await self._make_file_writable(item)
                    elif item.is_dir():
                        await self._make_directory_writable(item, False)

        except Exception as e:
            logger.error(f"Failed to make directory {path} writable: {e}")
            raise

    async def set_permissions(
        self,
        path: Union[str, Path],
        mode: int,
        recursive: bool = False
    ) -> None:
        """Set specific permissions on a path
        
        Args:
            path: Path to set permissions on
            mode: Permission mode (e.g., 0o755)
            recursive: Whether to apply recursively
            
        Raises:
            FileCleanupError: If permissions cannot be set
        """
        try:
            path = Path(path)
            if not path.exists():
                return

            if not self._is_windows:  # Skip on Windows
                os.chmod(path, mode)

                if recursive and path.is_dir():
                    file_mode = mode & ~stat.S_IXUSR & ~stat.S_IXGRP & ~stat.S_IXOTH
                    for item in path.rglob('*'):
                        if item.is_file():
                            os.chmod(item, file_mode)
                        elif item.is_dir():
                            os.chmod(item, mode)

        except Exception as e:
            logger.error(f"Error setting permissions for {path}: {e}")
            raise FileCleanupError(f"Failed to set permissions: {str(e)}")

    async def check_permissions(
        self,
        path: Union[str, Path],
        require_writable: bool = True,
        require_readable: bool = True,
        require_executable: bool = False
    ) -> bool:
        """Check if a path has required permissions
        
        Args:
            path: Path to check
            require_writable: Whether write permission is required
            require_readable: Whether read permission is required
            require_executable: Whether execute permission is required
            
        Returns:
            bool: True if path has required permissions
        """
        try:
            path = Path(path)
            if not path.exists():
                return False

            if require_readable and not os.access(path, os.R_OK):
                return False
            if require_writable and not os.access(path, os.W_OK):
                return False
            if require_executable and not os.access(path, os.X_OK):
                return False

            return True

        except Exception as e:
            logger.error(f"Error checking permissions for {path}: {e}")
            return False

    async def fix_permissions(
        self,
        path: Union[str, Path],
        recursive: bool = False
    ) -> List[str]:
        """Fix common permission issues on a path
        
        Args:
            path: Path to fix permissions on
            recursive: Whether to apply recursively
            
        Returns:
            List[str]: List of errors encountered
        """
        errors = []
        try:
            path = Path(path)
            if not path.exists():
                return errors

            if path.is_file():
                try:
                    await self.set_permissions(path, self.DEFAULT_FILE_MODE)
                except Exception as e:
                    errors.append(f"Error fixing file permissions for {path}: {str(e)}")
            elif path.is_dir():
                try:
                    await self.set_permissions(path, self.DEFAULT_DIR_MODE)
                    if recursive:
                        for item in path.rglob('*'):
                            try:
                                if item.is_file():
                                    await self.set_permissions(item, self.DEFAULT_FILE_MODE)
                                elif item.is_dir():
                                    await self.set_permissions(item, self.DEFAULT_DIR_MODE)
                            except Exception as e:
                                errors.append(f"Error fixing permissions for {item}: {str(e)}")
                except Exception as e:
                    errors.append(f"Error fixing directory permissions for {path}: {str(e)}")

        except Exception as e:
            errors.append(f"Error during permission fix: {str(e)}")

        return errors
