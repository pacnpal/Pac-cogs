"""Module for managing VideoArchiver lifecycle"""

import asyncio
import logging
from typing import Optional, Dict, Any, Set
from enum import Enum
from datetime import datetime

from .cleanup import cleanup_resources, force_cleanup_resources
from ..utils.exceptions import VideoArchiverError
from .initialization import initialize_cog, init_callback

logger = logging.getLogger("VideoArchiver")

class LifecycleState(Enum):
    """Possible states in the cog lifecycle"""
    UNINITIALIZED = "uninitialized"
    INITIALIZING = "initializing"
    READY = "ready"
    UNLOADING = "unloading"
    ERROR = "error"

class TaskManager:
    """Manages asyncio tasks"""

    def __init__(self):
        self._tasks: Dict[str, asyncio.Task] = {}
        self._task_history: Dict[str, Dict[str, Any]] = {}

    async def create_task(
        self,
        name: str,
        coro,
        callback=None
    ) -> asyncio.Task:
        """Create and track a task"""
        task = asyncio.create_task(coro)
        self._tasks[name] = task
        self._task_history[name] = {
            "start_time": datetime.utcnow(),
            "status": "running"
        }

        if callback:
            task.add_done_callback(lambda t: self._handle_completion(name, t, callback))
        else:
            task.add_done_callback(lambda t: self._handle_completion(name, t))

        return task

    def _handle_completion(
        self,
        name: str,
        task: asyncio.Task,
        callback=None
    ) -> None:
        """Handle task completion"""
        try:
            task.result()  # Raises exception if task failed
            status = "completed"
        except asyncio.CancelledError:
            status = "cancelled"
        except Exception as e:
            status = "failed"
            logger.error(f"Task {name} failed: {e}")

        self._task_history[name].update({
            "end_time": datetime.utcnow(),
            "status": status
        })

        if callback:
            try:
                callback(task)
            except Exception as e:
                logger.error(f"Task callback error for {name}: {e}")

        self._tasks.pop(name, None)

    async def cancel_task(self, name: str) -> None:
        """Cancel a specific task"""
        if task := self._tasks.get(name):
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    logger.error(f"Error cancelling task {name}: {e}")

    async def cancel_all_tasks(self) -> None:
        """Cancel all tracked tasks"""
        for name in list(self._tasks.keys()):
            await self.cancel_task(name)

    def get_task_status(self) -> Dict[str, Any]:
        """Get status of all tasks"""
        return {
            "active_tasks": list(self._tasks.keys()),
            "history": self._task_history.copy()
        }

class StateTracker:
    """Tracks lifecycle state and transitions"""

    def __init__(self):
        self.state = LifecycleState.UNINITIALIZED
        self.state_history: List[Dict[str, Any]] = []
        self._record_state()

    def set_state(self, state: LifecycleState) -> None:
        """Set current state"""
        self.state = state
        self._record_state()

    def _record_state(self) -> None:
        """Record state transition"""
        self.state_history.append({
            "state": self.state.value,
            "timestamp": datetime.utcnow()
        })

    def get_state_history(self) -> List[Dict[str, Any]]:
        """Get state transition history"""
        return self.state_history.copy()

class LifecycleManager:
    """Manages the lifecycle of the VideoArchiver cog"""

    def __init__(self, cog):
        self.cog = cog
        self.task_manager = TaskManager()
        self.state_tracker = StateTracker()
        self._cleanup_handlers: Set[callable] = set()

    def register_cleanup_handler(self, handler: callable) -> None:
        """Register a cleanup handler"""
        self._cleanup_handlers.add(handler)

    async def handle_load(self) -> None:
        """Handle cog loading without blocking"""
        try:
            self.state_tracker.set_state(LifecycleState.INITIALIZING)
            
            # Start initialization as background task
            await self.task_manager.create_task(
                "initialization",
                initialize_cog(self.cog),
                lambda t: init_callback(self.cog, t)
            )
            logger.info("Initialization started in background")
            
        except Exception as e:
            self.state_tracker.set_state(LifecycleState.ERROR)
            # Ensure cleanup on any error
            try:
                await asyncio.wait_for(
                    force_cleanup_resources(self.cog),
                    timeout=15  # CLEANUP_TIMEOUT
                )
            except asyncio.TimeoutError:
                logger.error("Force cleanup during load error timed out")
            raise VideoArchiverError(f"Error during cog load: {str(e)}")

    async def handle_unload(self) -> None:
        """Clean up when cog is unloaded"""
        self.state_tracker.set_state(LifecycleState.UNLOADING)
        
        try:
            # Cancel all tasks
            await self.task_manager.cancel_all_tasks()

            # Run cleanup handlers
            await self._run_cleanup_handlers()

            # Try normal cleanup
            try:
                cleanup_task = await self.task_manager.create_task(
                    "cleanup",
                    cleanup_resources(self.cog)
                )
                await asyncio.wait_for(cleanup_task, timeout=30)  # UNLOAD_TIMEOUT
                logger.info("Normal cleanup completed")
                
            except (asyncio.TimeoutError, Exception) as e:
                if isinstance(e, asyncio.TimeoutError):
                    logger.warning("Normal cleanup timed out, forcing cleanup")
                else:
                    logger.error(f"Error during normal cleanup: {str(e)}")

                # Force cleanup
                try:
                    await asyncio.wait_for(
                        force_cleanup_resources(self.cog),
                        timeout=15  # CLEANUP_TIMEOUT
                    )
                    logger.info("Force cleanup completed")
                except asyncio.TimeoutError:
                    logger.error("Force cleanup timed out")
                except Exception as e:
                    logger.error(f"Error during force cleanup: {str(e)}")

        except Exception as e:
            logger.error(f"Error during cog unload: {str(e)}")
            self.state_tracker.set_state(LifecycleState.ERROR)
        finally:
            # Clear all references
            await self._cleanup_references()

    async def _run_cleanup_handlers(self) -> None:
        """Run all registered cleanup handlers"""
        for handler in self._cleanup_handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler()
                else:
                    handler()
            except Exception as e:
                logger.error(f"Error in cleanup handler: {e}")

    async def _cleanup_references(self) -> None:
        """Clean up all references"""
        self.cog.ready.clear()
        self.cog.bot = None
        self.cog.processor = None
        self.cog.queue_manager = None
        self.cog.update_checker = None
        self.cog.ffmpeg_mgr = None
        self.cog.components.clear()
        self.cog.db = None

    def get_status(self) -> Dict[str, Any]:
        """Get current lifecycle status"""
        return {
            "state": self.state_tracker.state.value,
            "state_history": self.state_tracker.get_state_history(),
            "tasks": self.task_manager.get_task_status()
        }
