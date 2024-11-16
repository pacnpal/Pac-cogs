"""Event handlers for VideoArchiver"""

import asyncio
import logging
import traceback
from datetime import datetime
from enum import Enum, auto
from typing import TYPE_CHECKING, Dict, Any, Optional, TypedDict, ClassVar, List

import discord

from ..processor.constants import REACTIONS
from ..processor.reactions import handle_archived_reaction
from .guild import initialize_guild_components, cleanup_guild_components
from .error_handler import error_manager
from .response_handler import response_manager
from ..utils.exceptions import EventError, ErrorContext, ErrorSeverity

if TYPE_CHECKING:
    from .base import VideoArchiver

logger = logging.getLogger("VideoArchiver")


class EventType(Enum):
    """Types of Discord events"""
    GUILD_JOIN = auto()
    GUILD_REMOVE = auto()
    MESSAGE = auto()
    REACTION_ADD = auto()
    MESSAGE_PROCESSING = auto()
    REACTION_PROCESSING = auto()


class EventStats(TypedDict):
    """Type definition for event statistics"""
    counts: Dict[str, int]
    last_events: Dict[str, str]
    errors: Dict[str, int]
    error_rate: float
    health: bool


class EventHistory(TypedDict):
    """Type definition for event history entry"""
    event_type: str
    timestamp: str
    guild_id: Optional[int]
    channel_id: Optional[int]
    message_id: Optional[int]
    user_id: Optional[int]
    error: Optional[str]
    duration: float


class EventTracker:
    """Tracks event occurrences and patterns"""

    MAX_HISTORY: ClassVar[int] = 1000  # Maximum history entries to keep
    ERROR_THRESHOLD: ClassVar[float] = 0.1  # 10% error rate threshold

    def __init__(self) -> None:
        self.event_counts: Dict[str, int] = {}
        self.last_events: Dict[str, datetime] = {}
        self.error_counts: Dict[str, int] = {}
        self.history: List[EventHistory] = []

    def record_event(
        self,
        event_type: EventType,
        guild_id: Optional[int] = None,
        channel_id: Optional[int] = None,
        message_id: Optional[int] = None,
        user_id: Optional[int] = None,
    ) -> None:
        """Record an event occurrence"""
        event_name = event_type.name
        self.event_counts[event_name] = self.event_counts.get(event_name, 0) + 1
        self.last_events[event_name] = datetime.utcnow()

        # Add to history
        self.history.append(
            EventHistory(
                event_type=event_name,
                timestamp=datetime.utcnow().isoformat(),
                guild_id=guild_id,
                channel_id=channel_id,
                message_id=message_id,
                user_id=user_id,
                error=None,
                duration=0.0,
            )
        )

        # Cleanup old history
        if len(self.history) > self.MAX_HISTORY:
            self.history = self.history[-self.MAX_HISTORY:]

    def record_error(
        self, event_type: EventType, error: str, duration: float = 0.0
    ) -> None:
        """Record an event error"""
        event_name = event_type.name
        self.error_counts[event_name] = self.error_counts.get(event_name, 0) + 1

        # Update last history entry with error
        if self.history:
            self.history[-1].update({"error": error, "duration": duration})

    def get_stats(self) -> EventStats:
        """Get event statistics"""
        total_events = sum(self.event_counts.values())
        total_errors = sum(self.error_counts.values())
        error_rate = total_errors / total_events if total_events > 0 else 0.0

        return EventStats(
            counts=self.event_counts.copy(),
            last_events={k: v.isoformat() for k, v in self.last_events.items()},
            errors=self.error_counts.copy(),
            error_rate=error_rate,
            health=error_rate < self.ERROR_THRESHOLD,
        )


class GuildEventHandler:
    """Handles guild-related events"""

    def __init__(self, cog: "VideoArchiver", tracker: EventTracker) -> None:
        self.cog = cog
        self.tracker = tracker

    async def handle_guild_join(self, guild: discord.Guild) -> None:
        """
        Handle bot joining a new guild.

        Args:
            guild: Discord guild that was joined

        Raises:
            EventError: If guild initialization fails
        """
        start_time = datetime.utcnow()
        self.tracker.record_event(EventType.GUILD_JOIN, guild_id=guild.id)

        if not self.cog.ready.is_set():
            return

        try:
            await initialize_guild_components(self.cog, guild.id)
            logger.info(f"Initialized components for new guild {guild.id}")
        except Exception as e:
            duration = (datetime.utcnow() - start_time).total_seconds()
            self.tracker.record_error(EventType.GUILD_JOIN, str(e), duration)
            error = f"Failed to initialize new guild {guild.id}: {str(e)}"
            logger.error(error, exc_info=True)
            raise EventError(
                error,
                context=ErrorContext(
                    "GuildEventHandler",
                    "handle_guild_join",
                    {"guild_id": guild.id},
                    ErrorSeverity.HIGH,
                ),
            )

    async def handle_guild_remove(self, guild: discord.Guild) -> None:
        """
        Handle bot leaving a guild.

        Args:
            guild: Discord guild that was left

        Raises:
            EventError: If guild cleanup fails
        """
        start_time = datetime.utcnow()
        self.tracker.record_event(EventType.GUILD_REMOVE, guild_id=guild.id)

        try:
            await cleanup_guild_components(self.cog, guild.id)
        except Exception as e:
            duration = (datetime.utcnow() - start_time).total_seconds()
            self.tracker.record_error(EventType.GUILD_REMOVE, str(e), duration)
            error = f"Error cleaning up removed guild {guild.id}: {str(e)}"
            logger.error(error, exc_info=True)
            raise EventError(
                error,
                context=ErrorContext(
                    "GuildEventHandler",
                    "handle_guild_remove",
                    {"guild_id": guild.id},
                    ErrorSeverity.HIGH,
                ),
            )


class MessageEventHandler:
    """Handles message-related events"""

    def __init__(self, cog: "VideoArchiver", tracker: EventTracker) -> None:
        self.cog = cog
        self.tracker = tracker

    async def handle_message(self, message: discord.Message) -> None:
        """
        Handle new messages for video processing.

        Args:
            message: Discord message to process
        """
        self.tracker.record_event(
            EventType.MESSAGE,
            guild_id=message.guild.id if message.guild else None,
            channel_id=message.channel.id,
            message_id=message.id,
            user_id=message.author.id,
        )

        # Skip if not ready or if message is from DM/bot
        if not self.cog.ready.is_set() or message.guild is None or message.author.bot:
            return

        # Skip if message is a command
        ctx = await self.cog.bot.get_context(message)
        if ctx.valid:
            return

        # Process message in background task
        asyncio.create_task(self._process_message_background(message))

    async def _process_message_background(self, message: discord.Message) -> None:
        """Process message in background to avoid blocking"""
        start_time = datetime.utcnow()
        try:
            await self.cog.processor.process_message(message)
        except Exception as e:
            duration = (datetime.utcnow() - start_time).total_seconds()
            self.tracker.record_error(EventType.MESSAGE_PROCESSING, str(e), duration)
            await self._handle_processing_error(message, e)

    async def _handle_processing_error(
        self, message: discord.Message, error: Exception
    ) -> None:
        """Handle message processing errors"""
        logger.error(f"Error processing message {message.id}: {traceback.format_exc()}")
        try:
            log_channel = await self.cog.config_manager.get_channel(
                message.guild, "log"
            )
            if log_channel:
                await response_manager.send_response(
                    log_channel,
                    content=(
                        f"Error processing message: {str(error)}\n"
                        f"Message ID: {message.id}\n"
                        f"Channel: {message.channel.mention}"
                    ),
                    response_type=ErrorSeverity.HIGH,
                )
        except Exception as log_error:
            logger.error(f"Failed to log error to guild: {str(log_error)}")


class ReactionEventHandler:
    """Handles reaction-related events"""

    def __init__(self, cog: "VideoArchiver", tracker: EventTracker) -> None:
        self.cog = cog
        self.tracker = tracker

    async def handle_reaction_add(
        self, payload: discord.RawReactionActionEvent
    ) -> None:
        """
        Handle reactions to messages.

        Args:
            payload: Reaction event payload
        """
        self.tracker.record_event(
            EventType.REACTION_ADD,
            guild_id=payload.guild_id,
            channel_id=payload.channel_id,
            message_id=payload.message_id,
            user_id=payload.user_id,
        )

        if payload.user_id == self.cog.bot.user.id:
            return

        try:
            await self._process_reaction(payload)
        except Exception as e:
            self.tracker.record_error(EventType.REACTION_PROCESSING, str(e))
            logger.error(f"Error handling reaction: {e}", exc_info=True)

    async def _process_reaction(self, payload: discord.RawReactionActionEvent) -> None:
        """
        Process a reaction event.

        Args:
            payload: Reaction event payload

        Raises:
            EventError: If reaction processing fails
        """
        try:
            # Get the channel and message
            channel = self.cog.bot.get_channel(payload.channel_id)
            if not channel:
                return

            message = await channel.fetch_message(payload.message_id)
            if not message:
                return

            # Check if it's the archived reaction
            if str(payload.emoji) == REACTIONS["archived"]:
                # Only process if database is enabled
                if self.cog.db:
                    user = self.cog.bot.get_user(payload.user_id)
                    asyncio.create_task(
                        handle_archived_reaction(message, user, self.cog.db)
                    )

        except Exception as e:
            error = f"Failed to process reaction: {str(e)}"
            logger.error(error, exc_info=True)
            raise EventError(
                error,
                context=ErrorContext(
                    "ReactionEventHandler",
                    "_process_reaction",
                    {
                        "message_id": payload.message_id,
                        "user_id": payload.user_id,
                        "emoji": str(payload.emoji),
                    },
                    ErrorSeverity.MEDIUM,
                ),
            )


class EventManager:
    """Manages Discord event handling"""

    def __init__(self, cog: "VideoArchiver") -> None:
        self.tracker = EventTracker()
        self.guild_handler = GuildEventHandler(cog, self.tracker)
        self.message_handler = MessageEventHandler(cog, self.tracker)
        self.reaction_handler = ReactionEventHandler(cog, self.tracker)

    def get_stats(self) -> EventStats:
        """Get event statistics"""
        return self.tracker.get_stats()


def setup_events(cog: "VideoArchiver") -> EventManager:
    """
    Set up event handlers for the cog.

    Args:
        cog: VideoArchiver cog instance

    Returns:
        Configured EventManager instance
    """
    event_manager = EventManager(cog)

    @cog.listener()
    async def on_guild_join(guild: discord.Guild) -> None:
        await event_manager.guild_handler.handle_guild_join(guild)

    @cog.listener()
    async def on_guild_remove(guild: discord.Guild) -> None:
        await event_manager.guild_handler.handle_guild_remove(guild)

    @cog.listener()
    async def on_message(message: discord.Message) -> None:
        await event_manager.message_handler.handle_message(message)

    @cog.listener()
    async def on_raw_reaction_add(payload: discord.RawReactionActionEvent) -> None:
        await event_manager.reaction_handler.handle_reaction_add(payload)

    return event_manager
