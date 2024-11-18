"""Core type definitions and interfaces"""

from abc import ABC, abstractmethod
from enum import Enum, auto
from typing import Any, Dict, Optional, Protocol, TypedDict
from datetime import datetime

class ComponentState(Enum):
    """Component lifecycle states"""
    UNINITIALIZED = auto()
    INITIALIZING = auto()
    READY = auto()
    ERROR = auto()
    SHUTDOWN = auto()

class ProcessorState(Enum):
    """Processor states"""
    INITIALIZING = auto()
    READY = auto()
    PROCESSING = auto()
    PAUSED = auto()
    ERROR = auto()
    SHUTDOWN = auto()

class QueueState(Enum):
    """Queue states"""
    UNINITIALIZED = auto()
    INITIALIZING = auto()
    RUNNING = auto()
    PAUSED = auto()
    STOPPING = auto()
    STOPPED = auto()
    ERROR = auto()

class ComponentStatus(TypedDict):
    """Component status information"""
    state: str
    health: bool
    last_check: Optional[str]
    details: Dict[str, Any]

class IComponent(Protocol):
    """Interface for managed components"""
    
    @property
    def state(self) -> ComponentState:
        """Get component state"""
        ...

    async def initialize(self) -> None:
        """Initialize the component"""
        ...

    async def cleanup(self) -> None:
        """Clean up component resources"""
        ...

    def get_status(self) -> ComponentStatus:
        """Get component status"""
        ...

class IProcessor(IComponent, Protocol):
    """Interface for video processor"""
    
    async def process_video(self, item: Any) -> tuple[bool, Optional[str]]:
        """Process a video item"""
        ...

    async def process_message(self, message: Any) -> None:
        """Process a message"""
        ...

class IQueueManager(IComponent, Protocol):
    """Interface for queue management"""
    
    async def add_to_queue(
        self,
        url: str,
        message_id: int,
        channel_id: int,
        guild_id: int,
        author_id: int,
        priority: int = 0,
    ) -> bool:
        """Add item to queue"""
        ...

    def get_queue_status(self, guild_id: int) -> Dict[str, Any]:
        """Get queue status"""
        ...

class IConfigManager(IComponent, Protocol):
    """Interface for configuration management"""
    
    async def get_guild_settings(self, guild_id: int) -> Optional[Dict[str, Any]]:
        """Get guild settings"""
        ...

    async def update_guild_settings(self, guild_id: int, settings: Dict[str, Any]) -> None:
        """Update guild settings"""
        ...
