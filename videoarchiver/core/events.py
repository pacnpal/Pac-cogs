"""Event handlers for VideoArchiver"""

import logging
import discord
import asyncio
import traceback
from typing import TYPE_CHECKING, Dict, Any, Optional
from datetime import datetime

from ..processor.constants import REACTIONS
from ..processor.reactions import handle_archived_reaction
from .guild import initialize_guild_components, cleanup_guild_components
from .error_handler import error_manager
from .response_handler import response_manager

if TYPE_CHECKING:
    from .base import VideoArchiver

logger = logging.getLogger("VideoArchiver")

class EventTracker:
    """Tracks event occurrences and patterns"""

    def __init__(self):
        self.event_counts: Dict[str, int] = {}
        self.last_events: Dict[str, datetime] = {}
        self.error_counts: Dict[str, int] = {}

    def record_event(self, event_type: str) -> None:
        """Record an event occurrence"""
        self.event_counts[event_type] = self.event_counts.get(event_type, 0) + 1
        self.last_events[event_type] = datetime.utcnow()

    def record_error(self, event_type: str) -> None:
        """Record an event error"""
        self.error_counts[event_type] = self.error_counts.get(event_type, 0) + 1

    def get_stats(self) -> Dict[str, Any]:
        """Get event statistics"""
        return {
            "counts": self.event_counts.copy(),
            "last_events": {k: v.isoformat() for k, v in self.last_events.items()},
            "errors": self.error_counts.copy()
        }

class GuildEventHandler:
    """Handles guild-related events"""

    def __init__(self, cog: "VideoArchiver", tracker: EventTracker):
        self.cog = cog
        self.tracker = tracker

    async def handle_guild_join(self, guild: discord.Guild) -> None:
        """Handle bot joining a new guild"""
        self.tracker.record_event("guild_join")
        
        if not self.cog.ready.is_set():
            return

        try:
            await initialize_guild_components(self.cog, guild.id)
            logger.info(f"Initialized components for new guild {guild.id}")
        except Exception as e:
            self.tracker.record_error("guild_join")
            logger.error(f"Failed to initialize new guild {guild.id}: {str(e)}")

    async def handle_guild_remove(self, guild: discord.Guild) -> None:
        """Handle bot leaving a guild"""
        self.tracker.record_event("guild_remove")
        
        try:
            await cleanup_guild_components(self.cog, guild.id)
        except Exception as e:
            self.tracker.record_error("guild_remove")
            logger.error(f"Error cleaning up removed guild {guild.id}: {str(e)}")

class MessageEventHandler:
    """Handles message-related events"""

    def __init__(self, cog: "VideoArchiver", tracker: EventTracker):
        self.cog = cog
        self.tracker = tracker

    async def handle_message(self, message: discord.Message) -> None:
        """Handle new messages for video processing"""
        self.tracker.record_event("message")

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
        try:
            await self.cog.processor.process_message(message)
        except Exception as e:
            self.tracker.record_error("message_processing")
            await self._handle_processing_error(message, e)

    async def _handle_processing_error(
        self,
        message: discord.Message,
        error: Exception
    ) -> None:
        """Handle message processing errors"""
        logger.error(
            f"Error processing message {message.id}: {traceback.format_exc()}"
        )
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
                    response_type="error"
                )
        except Exception as log_error:
            logger.error(f"Failed to log error to guild: {str(log_error)}")

class ReactionEventHandler:
    """Handles reaction-related events"""

    def __init__(self, cog: "VideoArchiver", tracker: EventTracker):
        self.cog = cog
        self.tracker = tracker

    async def handle_reaction_add(
        self,
        payload: discord.RawReactionActionEvent
    ) -> None:
        """Handle reactions to messages"""
        self.tracker.record_event("reaction_add")

        if payload.user_id == self.cog.bot.user.id:
            return

        try:
            await self._process_reaction(payload)
        except Exception as e:
            self.tracker.record_error("reaction_processing")
            logger.error(f"Error handling reaction: {e}")

    async def _process_reaction(
        self,
        payload: discord.RawReactionActionEvent
    ) -> None:
        """Process a reaction event"""
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

class EventManager:
    """Manages Discord event handling"""

    def __init__(self, cog: "VideoArchiver"):
        self.tracker = EventTracker()
        self.guild_handler = GuildEventHandler(cog, self.tracker)
        self.message_handler = MessageEventHandler(cog, self.tracker)
        self.reaction_handler = ReactionEventHandler(cog, self.tracker)

    def get_stats(self) -> Dict[str, Any]:
        """Get event statistics"""
        return self.tracker.get_stats()

def setup_events(cog: "VideoArchiver") -> None:
    """Set up event handlers for the cog"""
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
