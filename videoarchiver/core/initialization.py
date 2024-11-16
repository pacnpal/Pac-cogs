"""Module for handling VideoArchiver initialization"""

from typing import TYPE_CHECKING
import asyncio

if TYPE_CHECKING:
    from .base import VideoArchiver

# Re-export initialization functions from lifecycle
async def initialize_cog(cog: "VideoArchiver") -> None:
    """Initialize all components with proper error handling"""
    await cog.lifecycle_manager.initialize_cog()

def init_callback(cog: "VideoArchiver", task: asyncio.Task) -> None:
    """Handle initialization task completion"""
    cog.lifecycle_manager.init_callback(task)
