"""Module for managing VideoArchiver lifecycle"""

import asyncio
import logging
import traceback
from typing import Optional, Dict, Any, Set, List, Callable, TypedDict, ClassVar, Union
from enum import Enum, auto
from datetime import datetime

from .cleanup import cleanup_resources, force_cleanup_resources
from ..utils.exceptions import (
    VideoArchiverError,
    ErrorContext,
    ErrorSeverity,
    ComponentError,
    CleanupError
)

logger = logging.getLogger("VideoArchiver")

class LifecycleState(Enum):
    """Possible states in the cog lifecycle"""
    UNINITIALIZED = auto()
    INITIALIZING = auto()
    READY = auto()
    UNLOADING = auto()
    ERROR = auto()

class TaskStatus(Enum):
    """Task execution status"""
    RUNNING = auto()
    COMPLETED = auto()
    CANCELLED = auto()
    FAILED = auto()

class TaskHistory(TypedDict):
    """Type definition for task history entry"""
    start_time: str
    end_time: Optional[str]
    status: str
    error: Optional[str]
    duration: float

class StateHistory(TypedDict):
    """Type definition for state history entry"""
    state: str
    timestamp: str
    duration: float
    details: Optional[Dict[str, Any]]

class LifecycleStatus(TypedDict):
    """Type definition for lifecycle status"""
    state: str
    state_history: List[StateHistory]
    tasks: Dict[str, Any]
    health: bool

class TaskManager:
    """Manages asyncio tasks"""

    TASK_TIMEOUT: ClassVar[int] = 30  # Default task timeout in seconds

    def __init__(self) -> None:
        self._tasks: Dict[str, asyncio.Task] = {}
        self._task_history: Dict[str, TaskHistory] = {}

    async def create_task(
        self,
        name: str,
        coro: Callable[..., Any],
        callback: Optional[Callable[[asyncio.Task], None]] = None,
        timeout: Optional[float] = None
    ) -> asyncio.Task:
        """
        Create and track a task.
        
        Args:
            name: Task name
            coro: Coroutine to run
            callback: Optional completion callback
            timeout: Optional timeout in seconds
            
        Returns:
            Created task
            
        Raises:
            ComponentError: If task creation fails
        """
        try:
            task = asyncio.create_task(coro)
            self._tasks[name] = task
            self._task_history[name] = TaskHistory(
                start_time=datetime.utcnow().isoformat(),
                end_time=None,
                status=TaskStatus.RUNNING.name,
                error=None,
                duration=0.0
            )

            if timeout:
                asyncio.create_task(self._handle_timeout(name, task, timeout))

            if callback:
                task.add_done_callback(lambda t: self._handle_completion(name, t, callback))
            else:
                task.add_done_callback(lambda t: self._handle_completion(name, t))

            return task

        except Exception as e:
            error = f"Failed to create task {name}: {str(e)}"
            logger.error(error, exc_info=True)
            raise ComponentError(
                error,
                context=ErrorContext(
                    "TaskManager",
                    "create_task",
                    {"task_name": name},
                    ErrorSeverity.HIGH
                )
            )

    async def _handle_timeout(
        self,
        name: str,
        task: asyncio.Task,
        timeout: float
    ) -> None:
        """Handle task timeout"""
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=timeout)
        except asyncio.TimeoutError:
            if not task.done():
                logger.warning(f"Task {name} timed out after {timeout}s")
                task.cancel()
                self._update_task_history(
                    name,
                    TaskStatus.FAILED,
                    f"Task timed out after {timeout}s"
                )

    def _handle_completion(
        self,
        name: str,
        task: asyncio.Task,
        callback: Optional[Callable[[asyncio.Task], None]] = None
    ) -> None:
        """Handle task completion"""
        try:
            task.result()  # Raises exception if task failed
            status = TaskStatus.COMPLETED
            error = None
        except asyncio.CancelledError:
            status = TaskStatus.CANCELLED
            error = "Task was cancelled"
        except Exception as e:
            status = TaskStatus.FAILED
            error = str(e)
            logger.error(f"Task {name} failed: {error}", exc_info=True)

        self._update_task_history(name, status, error)

        if callback:
            try:
                callback(task)
            except Exception as e:
                logger.error(f"Task callback error for {name}: {e}", exc_info=True)

        self._tasks.pop(name, None)

    def _update_task_history(
        self,
        name: str,
        status: TaskStatus,
        error: Optional[str] = None
    ) -> None:
        """Update task history entry"""
        if name in self._task_history:
            end_time = datetime.utcnow()
            start_time = datetime.fromisoformat(self._task_history[name]["start_time"])
            self._task_history[name].update({
                "end_time": end_time.isoformat(),
                "status": status.name,
                "error": error,
                "duration": (end_time - start_time).total_seconds()
            })

    async def cancel_task(self, name: str) -> None:
        """
        Cancel a specific task.
        
        Args:
            name: Task name to cancel
        """
        if task := self._tasks.get(name):
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    logger.error(f"Error cancelling task {name}: {e}", exc_info=True)

    async def cancel_all_tasks(self) -> None:
        """Cancel all tracked tasks"""
        for name in list(self._tasks.keys()):
            await self.cancel_task(name)

    def get_task_status(self) -> Dict[str, Any]:
        """
        Get status of all tasks.
        
        Returns:
            Dictionary containing task status information
        """
        return {
            "active_tasks": list(self._tasks.keys()),
            "history": self._task_history.copy()
        }

class StateTracker:
    """Tracks lifecycle state and transitions"""

    def __init__(self) -> None:
        self.state = LifecycleState.UNINITIALIZED
        self.state_history: List[StateHistory] = []
        self._record_state()

    def set_state(
        self,
        state: LifecycleState,
        details: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Set current state.
        
        Args:
            state: New state
            details: Optional state transition details
        """
        self.state = state
        self._record_state(details)

    def _record_state(
        self,
        details: Optional[Dict[str, Any]] = None
    ) -> None:
        """Record state transition"""
        now = datetime.utcnow()
        duration = 0.0
        if self.state_history:
            last_state = datetime.fromisoformat(self.state_history[-1]["timestamp"])
            duration = (now - last_state).total_seconds()

        self.state_history.append(StateHistory(
            state=self.state.name,
            timestamp=now.isoformat(),
            duration=duration,
            details=details
        ))

    def get_state_history(self) -> List[StateHistory]:
        """Get state transition history"""
        return self.state_history.copy()

class LifecycleManager:
    """Manages the lifecycle of the VideoArchiver cog"""

    INIT_TIMEOUT: ClassVar[int] = 60  # 1 minute timeout for initialization
    UNLOAD_TIMEOUT: ClassVar[int] = 30  # 30 seconds timeout for unloading
    CLEANUP_TIMEOUT: ClassVar[int] = 15  # 15 seconds timeout for cleanup

    def __init__(self, cog: Any) -> None:
        self.cog = cog
        self.task_manager = TaskManager()
        self.state_tracker = StateTracker()
        self._cleanup_handlers: Set[Callable] = set()

    def register_cleanup_handler(
        self,
        handler: Union[Callable[[], None], Callable[[], Any]]
    ) -> None:
        """
        Register a cleanup handler.
        
        Args:
            handler: Cleanup handler function
        """
        self._cleanup_handlers.add(handler)

    async def initialize_cog(self) -> None:
        """
        Initialize all components with proper error handling.
        
        Raises:
            ComponentError: If initialization fails
        """
        try:
            # Initialize components in sequence
            await self.cog.component_manager.initialize_components()
            
            # Set ready flag
            self.cog.ready.set()
            logger.info("VideoArchiver initialization completed successfully")

        except Exception as e:
            error = f"Error during initialization: {str(e)}"
            logger.error(error, exc_info=True)
            await cleanup_resources(self.cog)
            raise ComponentError(
                error,
                context=ErrorContext(
                    "LifecycleManager",
                    "initialize_cog",
                    None,
                    ErrorSeverity.HIGH
                )
            )

    def init_callback(self, task: asyncio.Task) -> None:
        """Handle initialization task completion"""
        try:
            task.result()
            logger.info("Initialization completed successfully")
            self.state_tracker.set_state(LifecycleState.READY)
        except asyncio.CancelledError:
            logger.warning("Initialization was cancelled")
            self.state_tracker.set_state(
                LifecycleState.ERROR,
                {"reason": "cancelled"}
            )
            asyncio.create_task(cleanup_resources(self.cog))
        except Exception as e:
            logger.error(f"Initialization failed: {str(e)}", exc_info=True)
            self.state_tracker.set_state(
                LifecycleState.ERROR,
                {"error": str(e)}
            )
            asyncio.create_task(cleanup_resources(self.cog))

    async def handle_load(self) -> None:
        """
        Handle cog loading without blocking.
        
        Raises:
            VideoArchiverError: If load fails
        """
        try:
            self.state_tracker.set_state(LifecycleState.INITIALIZING)
            
            # Start initialization as background task
            await self.task_manager.create_task(
                "initialization",
                self.initialize_cog(),
                self.init_callback,
                timeout=self.INIT_TIMEOUT
            )
            logger.info("Initialization started in background")
            
        except Exception as e:
            self.state_tracker.set_state(LifecycleState.ERROR)
            # Ensure cleanup on any error
            try:
                await asyncio.wait_for(
                    force_cleanup_resources(self.cog),
                    timeout=self.CLEANUP_TIMEOUT
                )
            except asyncio.TimeoutError:
                logger.error("Force cleanup during load error timed out")
            raise VideoArchiverError(
                f"Error during cog load: {str(e)}",
                context=ErrorContext(
                    "LifecycleManager",
                    "handle_load",
                    None,
                    ErrorSeverity.HIGH
                )
            )

    async def handle_unload(self) -> None:
        """
        Clean up when cog is unloaded.
        
        Raises:
            CleanupError: If cleanup fails
        """
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
                    cleanup_resources(self.cog),
                    timeout=self.UNLOAD_TIMEOUT
                )
                await cleanup_task
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
                        timeout=self.CLEANUP_TIMEOUT
                    )
                    logger.info("Force cleanup completed")
                except asyncio.TimeoutError:
                    error = "Force cleanup timed out"
                    logger.error(error)
                    raise CleanupError(
                        error,
                        context=ErrorContext(
                            "LifecycleManager",
                            "handle_unload",
                            None,
                            ErrorSeverity.CRITICAL
                        )
                    )
                except Exception as e:
                    error = f"Error during force cleanup: {str(e)}"
                    logger.error(error)
                    raise CleanupError(
                        error,
                        context=ErrorContext(
                            "LifecycleManager",
                            "handle_unload",
                            None,
                            ErrorSeverity.CRITICAL
                        )
                    )

        except Exception as e:
            error = f"Error during cog unload: {str(e)}"
            logger.error(error, exc_info=True)
            self.state_tracker.set_state(
                LifecycleState.ERROR,
                {"error": str(e)}
            )
            raise CleanupError(
                error,
                context=ErrorContext(
                    "LifecycleManager",
                    "handle_unload",
                    None,
                    ErrorSeverity.CRITICAL
                )
            )
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
                logger.error(f"Error in cleanup handler: {e}", exc_info=True)

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

    def get_status(self) -> LifecycleStatus:
        """
        Get current lifecycle status.
        
        Returns:
            Dictionary containing lifecycle status information
        """
        return LifecycleStatus(
            state=self.state_tracker.state.name,
            state_history=self.state_tracker.get_state_history(),
            tasks=self.task_manager.get_task_status(),
            health=self.state_tracker.state == LifecycleState.READY
        )
