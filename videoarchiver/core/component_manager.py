"""Module for managing VideoArchiver components"""

import logging
import asyncio
from typing import Dict, Any, Optional, Set, List, TypedDict, ClassVar, Type, Union, Protocol
from enum import Enum, auto
from datetime import datetime
from pathlib import Path
import importlib

from videoarchiver.utils.exceptions import (
    ComponentError,
    ErrorContext,
    ErrorSeverity
)
from videoarchiver.utils.path_manager import ensure_directory
from videoarchiver.config_manager import ConfigManager
from videoarchiver.processor.core import Processor
from videoarchiver.queue.manager import EnhancedVideoQueueManager
from videoarchiver.ffmpeg.ffmpeg_manager import FFmpegManager

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

class Initializable(Protocol):
    """Protocol for initializable components"""
    async def initialize(self) -> None:
        """Initialize the component"""
        ...

    async def shutdown(self) -> None:
        """Shutdown the component"""
        ...

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
        self,
        name: str,
        state: ComponentState,
        error: Optional[str] = None
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

        self.history.append(ComponentHistory(
            component=name,
            state=state.name,
            timestamp=now.isoformat(),
            error=error,
            duration=duration
        ))

        # Cleanup old history
        if len(self.history) > self.MAX_HISTORY:
            self.history = self.history[-self.MAX_HISTORY:]

    def get_component_history(self, name: str) -> List[ComponentHistory]:
        """Get state history for a component"""
        return [
            entry for entry in self.history
            if entry["component"] == name
        ]

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
                    ErrorSeverity.HIGH
                )
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
                has_path(dep, end)
                for dep in self.dependencies.get(start, set())
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
                    name for name in self.dependencies
                    if name in temp_visited
                )
                raise ComponentError(
                    f"Dependency cycle detected: {cycle}",
                    context=ErrorContext(
                        "DependencyManager",
                        "get_initialization_order",
                        {"cycle": cycle},
                        ErrorSeverity.HIGH
                    )
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
                    ErrorSeverity.HIGH
                )
            )

        return order

class ComponentManager:
    """Manages VideoArchiver components"""

    CORE_COMPONENTS: ClassVar[Dict[str, Tuple[Type[Any], Set[str]]]] = {
        "config_manager": (ConfigManager, set()),
        "processor": (Processor, {"config_manager"}),
        "queue_manager": (EnhancedVideoQueueManager, {"config_manager"}),
        "ffmpeg_mgr": (FFmpegManager, set())
    }

    def __init__(self, cog: Any) -> None:
        self.cog = cog
        self._components: Dict[str, Component] = {}
        self.tracker = ComponentTracker()
        self.dependency_manager = DependencyManager()

    def register(
        self,
        name: str,
        component: Union[Component, Any],
        dependencies: Optional[Set[str]] = None
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
                if isinstance(component, Initializable):
                    wrapped.initialize = component.initialize
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
                                ErrorSeverity.HIGH
                            )
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
                    ErrorSeverity.HIGH
                )
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
            
            # Get initialization order
            init_order = self.dependency_manager.get_initialization_order()
            
            # Initialize remaining components
            for name in init_order:
                if name not in self._components:
                    continue
                    
                component = self._components[name]
                try:
                    self.tracker.update_state(name, ComponentState.INITIALIZING)
                    await component.initialize()
                    component.initialization_time = datetime.utcnow()
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
                            ErrorSeverity.HIGH
                        )
                    )

        except Exception as e:
            error = f"Component initialization failed: {str(e)}"
            logger.error(error, exc_info=True)
            raise ComponentError(
                error,
                context=ErrorContext(
                    "ComponentManager",
                    "initialize_components",
                    None,
                    ErrorSeverity.HIGH
                )
            )

    async def _initialize_core_components(self) -> None:
        """
        Initialize core system components.
        
        Raises:
            ComponentError: If core component initialization fails
        """
        try:
            for name, (component_class, deps) in self.CORE_COMPONENTS.items():
                if name == "processor":
                    component = component_class(self.cog)
                elif name == "ffmpeg_mgr":
                    component = component_class(self.cog)
                else:
                    component = component_class()

                self.register(name, component, deps)

            # Initialize paths
            await self._initialize_paths()

        except Exception as e:
            error = f"Failed to initialize core components: {str(e)}"
            logger.error(error, exc_info=True)
            raise ComponentError(
                error,
                context=ErrorContext(
                    "ComponentManager",
                    "_initialize_core_components",
                    None,
                    ErrorSeverity.HIGH
                )
            )

    async def _initialize_paths(self) -> None:
        """
        Initialize required paths.
        
        Raises:
            ComponentError: If path initialization fails
        """
        try:
            data_dir = Path(self.cog.bot.data_path) / "VideoArchiver"
            download_dir = data_dir / "downloads"

            # Ensure directories exist
            await ensure_directory(data_dir)
            await ensure_directory(download_dir)

            # Register paths
            self.register("data_path", data_dir)
            self.register("download_path", download_dir)

        except Exception as e:
            error = f"Failed to initialize paths: {str(e)}"
            logger.error(error, exc_info=True)
            raise ComponentError(
                error,
                context=ErrorContext(
                    "ComponentManager",
                    "_initialize_paths",
                    None,
                    ErrorSeverity.HIGH
                )
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
            shutdown_order = reversed(self.dependency_manager.get_initialization_order())
            
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
                            ErrorSeverity.HIGH
                        )
                    )

        except Exception as e:
            error = f"Component shutdown failed: {str(e)}"
            logger.error(error, exc_info=True)
            raise ComponentError(
                error,
                context=ErrorContext(
                    "ComponentManager",
                    "shutdown_components",
                    None,
                    ErrorSeverity.HIGH
                )
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
                registration_time=component.registration_time.isoformat() if component.registration_time else None,
                initialization_time=component.initialization_time.isoformat() if component.initialization_time else None,
                dependencies=self.dependency_manager.get_dependencies(name),
                dependents=self.dependency_manager.get_dependents(name),
                error=component.error,
                health=component.is_healthy()
            )
            for name, component in self._components.items()
        }
