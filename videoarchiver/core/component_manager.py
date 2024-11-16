"""Module for managing VideoArchiver components"""

import logging
import asyncio
from typing import Dict, Any, Optional, Set, List
from enum import Enum
from datetime import datetime

logger = logging.getLogger("VideoArchiver")

class ComponentState(Enum):
    """Possible states of a component"""
    UNREGISTERED = "unregistered"
    REGISTERED = "registered"
    INITIALIZING = "initializing"
    READY = "ready"
    ERROR = "error"
    SHUTDOWN = "shutdown"

class ComponentDependencyError(Exception):
    """Raised when component dependencies cannot be satisfied"""
    pass

class ComponentLifecycleError(Exception):
    """Raised when component lifecycle operations fail"""
    pass

class Component:
    """Base class for managed components"""

    def __init__(self, name: str):
        self.name = name
        self.state = ComponentState.UNREGISTERED
        self.dependencies: Set[str] = set()
        self.dependents: Set[str] = set()
        self.registration_time: Optional[datetime] = None
        self.initialization_time: Optional[datetime] = None
        self.error: Optional[str] = None

    async def initialize(self) -> None:
        """Initialize the component"""
        pass

    async def shutdown(self) -> None:
        """Shutdown the component"""
        pass

class ComponentTracker:
    """Tracks component states and relationships"""

    def __init__(self):
        self.states: Dict[str, ComponentState] = {}
        self.history: List[Dict[str, Any]] = []

    def update_state(self, name: str, state: ComponentState, error: Optional[str] = None) -> None:
        """Update component state"""
        self.states[name] = state
        self.history.append({
            "component": name,
            "state": state.value,
            "timestamp": datetime.utcnow(),
            "error": error
        })

    def get_component_history(self, name: str) -> List[Dict[str, Any]]:
        """Get state history for a component"""
        return [
            entry for entry in self.history
            if entry["component"] == name
        ]

class DependencyManager:
    """Manages component dependencies"""

    def __init__(self):
        self.dependencies: Dict[str, Set[str]] = {}
        self.dependents: Dict[str, Set[str]] = {}

    def add_dependency(self, component: str, dependency: str) -> None:
        """Add a dependency relationship"""
        if component not in self.dependencies:
            self.dependencies[component] = set()
        self.dependencies[component].add(dependency)

        if dependency not in self.dependents:
            self.dependents[dependency] = set()
        self.dependents[dependency].add(component)

    def get_dependencies(self, component: str) -> Set[str]:
        """Get dependencies for a component"""
        return self.dependencies.get(component, set())

    def get_dependents(self, component: str) -> Set[str]:
        """Get components that depend on this component"""
        return self.dependents.get(component, set())

    def get_initialization_order(self) -> List[str]:
        """Get components in dependency order"""
        visited = set()
        order = []

        def visit(component: str) -> None:
            if component in visited:
                return
            visited.add(component)
            for dep in self.dependencies.get(component, set()):
                visit(dep)
            order.append(component)

        for component in self.dependencies:
            visit(component)

        return order

class ComponentManager:
    """Manages VideoArchiver components"""

    def __init__(self, cog):
        self.cog = cog
        self._components: Dict[str, Component] = {}
        self.tracker = ComponentTracker()
        self.dependency_manager = DependencyManager()

    def register(
        self,
        name: str,
        component: Any,
        dependencies: Optional[Set[str]] = None
    ) -> None:
        """Register a component with dependencies"""
        try:
            # Wrap non-Component objects
            if not isinstance(component, Component):
                component = Component(name)

            # Register dependencies
            if dependencies:
                for dep in dependencies:
                    if dep not in self._components:
                        raise ComponentDependencyError(
                            f"Dependency {dep} not registered for {name}"
                        )
                    self.dependency_manager.add_dependency(name, dep)

            # Register component
            self._components[name] = component
            component.registration_time = datetime.utcnow()
            self.tracker.update_state(name, ComponentState.REGISTERED)
            logger.debug(f"Registered component: {name}")

        except Exception as e:
            logger.error(f"Error registering component {name}: {e}")
            self.tracker.update_state(name, ComponentState.ERROR, str(e))
            raise ComponentLifecycleError(f"Failed to register component: {str(e)}")

    async def initialize_components(self) -> None:
        """Initialize all components in dependency order"""
        try:
            # Get initialization order
            init_order = self.dependency_manager.get_initialization_order()
            
            # Initialize core components first
            await self._initialize_core_components()
            
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
                    logger.error(f"Error initializing component {name}: {e}")
                    self.tracker.update_state(name, ComponentState.ERROR, str(e))
                    raise ComponentLifecycleError(
                        f"Failed to initialize component {name}: {str(e)}"
                    )

        except Exception as e:
            logger.error(f"Error during component initialization: {e}")
            raise ComponentLifecycleError(f"Component initialization failed: {str(e)}")

    async def _initialize_core_components(self) -> None:
        """Initialize core system components"""
        from ..config_manager import ConfigManager
        from ..processor.core import Processor
        from ..queue.manager import QueueManager
        from ..ffmpeg.ffmpeg_manager import FFmpegManager

        core_components = {
            "config_manager": (ConfigManager(self.cog), set()),
            "processor": (Processor(self.cog), {"config_manager"}),
            "queue_manager": (QueueManager(self.cog), {"config_manager"}),
            "ffmpeg_mgr": (FFmpegManager(self.cog), set())
        }

        for name, (component, deps) in core_components.items():
            self.register(name, component, deps)

        # Initialize paths
        await self._initialize_paths()

    async def _initialize_paths(self) -> None:
        """Initialize required paths"""
        from pathlib import Path
        from ..utils.path_manager import ensure_directory

        data_dir = Path(self.cog.bot.data_path) / "VideoArchiver"
        download_dir = data_dir / "downloads"

        # Ensure directories exist
        await ensure_directory(data_dir)
        await ensure_directory(download_dir)

        # Register paths
        self.register("data_path", data_dir)
        self.register("download_path", download_dir)

    def get(self, name: str) -> Optional[Any]:
        """Get a registered component"""
        component = self._components.get(name)
        return component if isinstance(component, Component) else None

    async def shutdown_components(self) -> None:
        """Shutdown components in reverse dependency order"""
        shutdown_order = reversed(self.dependency_manager.get_initialization_order())
        
        for name in shutdown_order:
            if name not in self._components:
                continue
                
            component = self._components[name]
            try:
                await component.shutdown()
                self.tracker.update_state(name, ComponentState.SHUTDOWN)
            except Exception as e:
                logger.error(f"Error shutting down component {name}: {e}")
                self.tracker.update_state(name, ComponentState.ERROR, str(e))

    def clear(self) -> None:
        """Clear all registered components"""
        self._components.clear()
        logger.debug("Cleared all components")

    def get_component_status(self) -> Dict[str, Any]:
        """Get status of all components"""
        return {
            name: {
                "state": self.tracker.states.get(name, ComponentState.UNREGISTERED).value,
                "registration_time": component.registration_time,
                "initialization_time": component.initialization_time,
                "dependencies": self.dependency_manager.get_dependencies(name),
                "dependents": self.dependency_manager.get_dependents(name),
                "error": component.error
            }
            for name, component in self._components.items()
        }
