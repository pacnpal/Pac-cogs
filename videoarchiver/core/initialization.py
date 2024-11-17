"""Module for handling VideoArchiver initialization"""

from typing import TYPE_CHECKING, Optional, Dict, Any
import asyncio
import logging

from videoarchiver.utils.exceptions import (
    ComponentError,
    ErrorContext,
    ErrorSeverity
)
from videoarchiver.core.lifecycle import LifecycleState

if TYPE_CHECKING:
    from videoarchiver.core.base import VideoArchiver

logger = logging.getLogger("VideoArchiver")

async def initialize_cog(cog: "VideoArchiver") -> None:
    """
    Initialize all components with proper error handling.
    
    This is a re-export of lifecycle_manager.initialize_cog with additional
    error context and logging.
    
    Args:
        cog: VideoArchiver cog instance
        
    Raises:
        ComponentError: If initialization fails
    """
    try:
        logger.info("Starting cog initialization...")
        await cog.lifecycle_manager.initialize_cog()
        logger.info("Cog initialization completed successfully")
    except Exception as e:
        error = f"Failed to initialize cog: {str(e)}"
        logger.error(error, exc_info=True)
        raise ComponentError(
            error,
            context=ErrorContext(
                "Initialization",
                "initialize_cog",
                {"state": cog.lifecycle_manager.state_tracker.state.name},
                ErrorSeverity.HIGH
            )
        )

def init_callback(cog: "VideoArchiver", task: asyncio.Task) -> None:
    """
    Handle initialization task completion.
    
    This is a re-export of lifecycle_manager.init_callback with additional
    error context and logging.
    
    Args:
        cog: VideoArchiver cog instance
        task: Initialization task
    """
    try:
        logger.debug("Processing initialization task completion...")
        cog.lifecycle_manager.init_callback(task)
        
        # Log final state
        state = cog.lifecycle_manager.state_tracker.state
        if state == LifecycleState.READY:
            logger.info("Initialization completed successfully")
        elif state == LifecycleState.ERROR:
            logger.error("Initialization failed")
        else:
            logger.warning(f"Unexpected state after initialization: {state.name}")
            
    except Exception as e:
        logger.error(f"Error in initialization callback: {str(e)}", exc_info=True)
        # We don't raise here since this is a callback

def get_init_status(cog: "VideoArchiver") -> Dict[str, Any]:
    """
    Get initialization status information.
    
    Args:
        cog: VideoArchiver cog instance
        
    Returns:
        Dictionary containing initialization status
    """
    return {
        "state": cog.lifecycle_manager.state_tracker.state.name,
        "ready": cog.ready.is_set(),
        "components_initialized": all(
            hasattr(cog, attr) and getattr(cog, attr) is not None
            for attr in [
                "processor",
                "queue_manager",
                "update_checker",
                "ffmpeg_mgr",
                "components",
                "db"
            ]
        ),
        "history": cog.lifecycle_manager.state_tracker.get_state_history()
    }
