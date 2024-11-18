"""Core module for VideoArchiver cog"""

try:
    # Try relative imports first
    from .base import VideoArchiver
except ImportError:
    # Fall back to absolute imports if relative imports fail
    # from videoarchiver.core.base import VideoArchiver

__all__ = ["VideoArchiver"]
