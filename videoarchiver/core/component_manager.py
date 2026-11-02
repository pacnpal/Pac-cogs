"""Module for managing VideoArchiver components"""

import logging
import asyncio
import contextlib
from typing import (
    Dict,
    Any,
    Optional,
    Set,
    List,
    Tuple,
    TypedDict,
    ClassVar,
    Type,
    Union,
    Protocol,
)
from enum import Enum, auto
from datetime import datetime
from pathlib import Path
import importlib

from redbot.core.data_manager import cog_data_path  # type: ignore

# try:
# Try relative imports first
from ..utils.exceptions import ComponentError, ErrorContext, ErrorSeverity
from ..utils.path_manager import PathManager
from ..config_manager import ConfigManager
from ..processor.core import VideoProcessor
from ..queue.manager import EnhancedVideoQueueManager, QueueConfig
from ..ffmpeg.ffmpeg_manager import FFmpegManager
from ..update_checker import UpdateChecker
from .guild import initialize_guild_components

# except ImportError:
# Fall back to absolute imports if relative imports fail
# from videoarchiver.utils.exceptions import ComponentError, ErrorContext, ErrorSeverity
# from videoarchiver.utils.path_manager import PathManager
# from videoarchiver.config_manager import ConfigManager
# from videoarchiver.processor.core import VideoProcessor
# from videoarchiver.queue.manager import EnhancedVideoQueueManager
# from videoarchiver.ffmpeg.ffmpeg_manager import FFmpegManager

logger = logging.getLogger("VideoArchiver")


class ComponentState(Enum):
    """Possible states of a component"""

    UNREGISTERED = auto()
    REGISTERED = auto()
    INITIALIZING = auto()
    READY = auto()
    ERROR = auto()
    SHUTDOWN = auto()


class ComponentHistory(TypedDict):
    """Type definition for component history entry"""

    component: str
    state: str
    timestamp: str
    error: Optional[str]
    duration: float


class ComponentStatus(TypedDict):
    """Type definition for component status"""

    state: str
    registration_time: Optional[str]
    initialization_time: Optional[str]
    dependencies: Set[str]
    dependents: Set[str]
    error: Optional[str]
    health: bool


class Component:
    """Base class for managed components"""

    def __init__(self, name: str) -> None:
        self.name = name
        self.state = ComponentState.UNREGISTERED
        self.dependencies: Set[str] = set()
        self.dependents: Set[str] = set()
        self.registration_time: Optional[datetime] = None
        self.initialization_time: Optional[datetime] = None
        self.error: Optional[str] = None
        self._health_check_task: Optional[asyncio.Task] = None
        self.instance: Any = self  # the real object a wrapper stands for

    async def initialize(self) -> None:
        """
        Initialize the component.

        Raises:
            ComponentError: If initialization fails
        """
        pass

    async def shutdown(self) -> None:
        """
        Shutdown the component.

        Raises:
            ComponentError: If shutdown fails
        """
        if self._health_check_task:
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass

    def is_healthy(self) -> bool:
        """Check if component is healthy"""
        return self.state == ComponentState.READY and not self.error


class ComponentTracker:
    """Tracks component states and relationships"""

    MAX_HISTORY: ClassVar[int] = 1000  # Maximum history entries to keep

    def __init__(self) -> None:
        self.states: Dict[str, ComponentState] = {}
        self.history: List[ComponentHistory] = []

    def update_state(
        self, name: str, state: ComponentState, error: Optional[str] = None
    ) -> None:
        """Update component state"""
        self.states[name] = state

        # Add history entry
        now = datetime.utcnow()
        duration = 0.0
        if self.history:
            last_entry = self.history[-1]
            last_time = datetime.fromisoformat(last_entry["timestamp"])
            duration = (now - last_time).total_seconds()

        self.history.append(
            ComponentHistory(
                component=name,
                state=state.name,
                timestamp=now.isoformat(),
                error=error,
                duration=duration,
            )
        )

        # Cleanup old history
        if len(self.history) > self.MAX_HISTORY:
            self.history = self.history[-self.MAX_HISTORY :]

    def get_component_history(self, name: str) -> List[ComponentHistory]:
        """Get state history for a component"""
        return [entry for entry in self.history if entry["component"] == name]


class DependencyManager:
    """Manages component dependencies"""

    def __init__(self) -> None:
        self.dependencies: Dict[str, Set[str]] = {}
        self.dependents: Dict[str, Set[str]] = {}

    def add_dependency(self, component: str, dependency: str) -> None:
        """
        Add a dependency relationship.

        Args:
            component: Component name
            dependency: Dependency name

        Raises:
            ComponentError: If dependency cycle is detected
        """
        # Check for cycles
        if self._would_create_cycle(component, dependency):
            raise ComponentError(
                f"Dependency cycle detected: {component} -> {dependency}",
                context=ErrorContext(
                    "DependencyManager",
                    "add_dependency",
                    {"component": component, "dependency": dependency},
                    ErrorSeverity.HIGH,
                ),
            )

        if component not in self.dependencies:
            self.dependencies[component] = set()
        self.dependencies[component].add(dependency)

        if dependency not in self.dependents:
            self.dependents[dependency] = set()
        self.dependents[dependency].add(component)

    def _would_create_cycle(self, component: str, dependency: str) -> bool:
        """Check if adding dependency would create a cycle"""
        visited = set()

        def has_path(start: str, end: str) -> bool:
            if start == end:
                return True
            if start in visited:
                return False
            visited.add(start)
            return any(
                has_path(dep, end) for dep in self.dependencies.get(start, set())
            )

        return has_path(dependency, component)

    def get_dependencies(self, component: str) -> Set[str]:
        """Get dependencies for a component"""
        return self.dependencies.get(component, set())

    def get_dependents(self, component: str) -> Set[str]:
        """Get components that depend on this component"""
        return self.dependents.get(component, set())

    def get_initialization_order(self) -> List[str]:
        """
        Get components in dependency order.

        Returns:
            List of component names in initialization order

        Raises:
            ComponentError: If dependency cycle is detected
        """
        visited: Set[str] = set()
        temp_visited: Set[str] = set()
        order: List[str] = []

        def visit(component: str) -> None:
            if component in temp_visited:
                cycle = " -> ".join(
                    name for name in self.dependencies if name in temp_visited
                )
                raise ComponentError(
                    f"Dependency cycle detected: {cycle}",
                    context=ErrorContext(
                        "DependencyManager",
                        "get_initialization_order",
                        {"cycle": cycle},
                        ErrorSeverity.HIGH,
                    ),
                )
            if component in visited:
                return

            temp_visited.add(component)
            for dep in self.dependencies.get(component, set()):
                visit(dep)
            temp_visited.remove(component)
            visited.add(component)
            order.append(component)

        try:
            for component in self.dependencies:
                if component not in visited:
                    visit(component)
        except RecursionError:
            raise ComponentError(
                "Dependency resolution exceeded maximum recursion depth",
                context=ErrorContext(
                    "DependencyManager",
                    "get_initialization_order",
                    None,
                    ErrorSeverity.HIGH,
                ),
            )

        return order


class ComponentManager:
    """Manages VideoArchiver components"""

    def __init__(self, cog: Any) -> None:
        self.cog = cog
        self._components: Dict[str, Component] = {}
        self.tracker = ComponentTracker()
        self.dependency_manager = DependencyManager()
        self.path_manager = PathManager()  # Create an instance of PathManager

    def register(
        self,
        name: str,
        component: Union[Component, Any],
        dependencies: Optional[Set[str]] = None,
    ) -> None:
        """
        Register a component with dependencies.

        Args:
            name: Component name
            component: Component instance
            dependencies: Optional set of dependency names

        Raises:
            ComponentError: If registration fails
        """
        try:
            # Wrap non-Component objects
            if not isinstance(component, Component):
                wrapped = Component(name)
                wrapped.instance = component
                if hasattr(component, "initialize"):
                    wrapped.initialize = component.initialize
                if hasattr(component, "shutdown"):
                    wrapped.shutdown = component.shutdown
                component = wrapped

            # Register dependencies
            if dependencies:
                for dep in dependencies:
                    if dep not in self._components:
                        raise ComponentError(
                            f"Dependency {dep} not registered for {name}",
                            context=ErrorContext(
                                "ComponentManager",
                                "register",
                                {"component": name, "dependency": dep},
                                ErrorSeverity.HIGH,
                            ),
                        )
                    self.dependency_manager.add_dependency(name, dep)

            # Register component
            self._components[name] = component
            component.registration_time = datetime.utcnow()
            self.tracker.update_state(name, ComponentState.REGISTERED)
            logger.debug(f"Registered component: {name}")

        except Exception as e:
            error = f"Failed to register component {name}: {str(e)}"
            logger.error(error, exc_info=True)
            self.tracker.update_state(name, ComponentState.ERROR, str(e))
            raise ComponentError(
                error,
                context=ErrorContext(
                    "ComponentManager",
                    "register",
                    {"component": name},
                    ErrorSeverity.HIGH,
                ),
            )

    async def initialize_components(self) -> None:
        """
        Initialize all components in dependency order.

        Raises:
            ComponentError: If initialization fails
        """
        try:
            # Initialize core components first
            await self._initialize_core_components()

            # Get initialization order (components with no dependency edges go last)
            init_order = self.dependency_manager.get_initialization_order()
            init_order += [n for n in self._components if n not in init_order]

            # Initialize remaining components
            for name in init_order:
                if name not in self._components:
                    continue

                component = self._components[name]
                try:
                    self.tracker.update_state(name, ComponentState.INITIALIZING)
                    await component.initialize()
                    component.initialization_time = datetime.utcnow()
                    component.state = ComponentState.READY
                    self.tracker.update_state(name, ComponentState.READY)
                except Exception as e:
                    error = f"Failed to initialize component {name}: {str(e)}"
                    logger.error(error, exc_info=True)
                    self.tracker.update_state(name, ComponentState.ERROR, str(e))
                    raise ComponentError(
                        error,
                        context=ErrorContext(
                            "ComponentManager",
                            "initialize_components",
                            {"component": name},
                            ErrorSeverity.HIGH,
                        ),
                    )

            # Both are up: run the queue loop with the processor's item handler.
            # queue_manager.cleanup()/force_stop() and processor.cleanup() cancel it.
            queue_manager = self._components["queue_manager"].instance
            processor = self._components["processor"].instance

            async def process_queue() -> None:
                # Cogs load before the gateway connects; items (persisted ones too) need
                # the guild/channel cache and each guild's downloader first
                await self.cog.bot.wait_until_red_ready()
                for guild in self.cog.bot.guilds:
                    if guild.id not in self.cog.components:
                        with contextlib.suppress(Exception):  # logged by the call
                            await initialize_guild_components(self.cog, guild.id)
                await queue_manager.processor.start_processing(processor.process_video)

            queue_manager._processing_task = asyncio.create_task(process_queue())
            processor.set_queue_task(queue_manager._processing_task)

        except Exception as e:
            error = f"Component initialization failed: {str(e)}"
            logger.error(error, exc_info=True)
            raise ComponentError(
                error,
                context=ErrorContext(
                    "ComponentManager",
                    "initialize_components",
                    None,
                    ErrorSeverity.HIGH,
                ),
            )

    async def _initialize_core_components(self) -> None:
        """
        Initialize core system components.

        Raises:
            ComponentError: If core component initialization fails
        """
        try:
            cog = self.cog
            # Paths first: the queue persists its state under the data dir
            data_dir = await self._initialize_paths()

            config_manager = ConfigManager(cog.config)
            self.register("config_manager", config_manager)

            # FFmpegManager.__init__ does blocking binary/GPU setup
            ffmpeg_mgr = await asyncio.to_thread(FFmpegManager)
            self.register("ffmpeg_mgr", ffmpeg_mgr)

            queue_manager = EnhancedVideoQueueManager(
                QueueConfig(persistence_path=str(data_dir / "queue_state.json"))
            )
            self.register("queue_manager", queue_manager, {"config_manager"})

            processor = VideoProcessor(
                cog.bot, config_manager, cog.components, queue_manager, ffmpeg_mgr, cog.db
            )
            self.register(
                "processor",
                processor,
                {"config_manager", "queue_manager", "ffmpeg_mgr"},
            )

            # Upgrades yt-dlp now (in the background) and then daily
            cog.update_checker = UpdateChecker()
            await cog.update_checker.start()

        except Exception as e:
            error = f"Failed to initialize core components: {str(e)}"
            logger.error(error, exc_info=True)
            raise ComponentError(
                error,
                context=ErrorContext(
                    "ComponentManager",
                    "_initialize_core_components",
                    None,
                    ErrorSeverity.HIGH,
                ),
            )

    async def _initialize_paths(self) -> Path:
        """
        Initialize required paths.

        Raises:
            ComponentError: If path initialization fails
        """
        try:
            data_dir = cog_data_path(self.cog)
            download_dir = data_dir / "downloads"

            # Ensure directories exist
            await self.path_manager.ensure_directory(data_dir)
            await self.path_manager.ensure_directory(download_dir)

            # Register paths
            self.register("data_path", data_dir)
            self.register("download_path", download_dir)
            return data_dir

        except Exception as e:
            error = f"Failed to initialize paths: {str(e)}"
            logger.error(error, exc_info=True)
            raise ComponentError(
                error,
                context=ErrorContext(
                    "ComponentManager", "_initialize_paths", None, ErrorSeverity.HIGH
                ),
            )

    def get(self, name: str) -> Optional[Component]:
        """Get a registered component"""
        return self._components.get(name)

    async def shutdown_components(self) -> None:
        """
        Shutdown components in reverse dependency order.

        Raises:
            ComponentError: If shutdown fails
        """
        try:
            shutdown_order = reversed(
                self.dependency_manager.get_initialization_order()
            )

            for name in shutdown_order:
                if name not in self._components:
                    continue

                component = self._components[name]
                try:
                    await component.shutdown()
                    self.tracker.update_state(name, ComponentState.SHUTDOWN)
                except Exception as e:
                    error = f"Error shutting down component {name}: {str(e)}"
                    logger.error(error, exc_info=True)
                    self.tracker.update_state(name, ComponentState.ERROR, str(e))
                    raise ComponentError(
                        error,
                        context=ErrorContext(
                            "ComponentManager",
                            "shutdown_components",
                            {"component": name},
                            ErrorSeverity.HIGH,
                        ),
                    )

        except Exception as e:
            error = f"Component shutdown failed: {str(e)}"
            logger.error(error, exc_info=True)
            raise ComponentError(
                error,
                context=ErrorContext(
                    "ComponentManager", "shutdown_components", None, ErrorSeverity.HIGH
                ),
            )

    def clear(self) -> None:
        """Clear all registered components"""
        self._components.clear()
        logger.debug("Cleared all components")

    def get_component_status(self) -> Dict[str, ComponentStatus]:
        """
        Get status of all components.

        Returns:
            Dictionary mapping component names to their status
        """
        return {
            name: ComponentStatus(
                state=self.tracker.states.get(name, ComponentState.UNREGISTERED).name,
                registration_time=(
                    component.registration_time.isoformat()
                    if component.registration_time
                    else None
                ),
                initialization_time=(
                    component.initialization_time.isoformat()
                    if component.initialization_time
                    else None
                ),
                dependencies=self.dependency_manager.get_dependencies(name),
                dependents=self.dependency_manager.get_dependents(name),
                error=component.error,
                health=component.is_healthy(),
            )
            for name, component in self._components.items()
        }
