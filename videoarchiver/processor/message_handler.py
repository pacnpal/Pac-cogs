"""Message processing and URL extraction for VideoProcessor"""

import logging
import asyncio
from enum import Enum
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime
import discord

from .url_extractor import URLExtractor
from .message_validator import MessageValidator
from .queue_processor import QueueProcessor
from .reactions import REACTIONS

logger = logging.getLogger("VideoArchiver")

class MessageState(Enum):
    """Possible states of message processing"""
    RECEIVED = "received"
    VALIDATING = "validating"
    EXTRACTING = "extracting"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    IGNORED = "ignored"

class ProcessingStage(Enum):
    """Message processing stages"""
    VALIDATION = "validation"
    EXTRACTION = "extraction"
    QUEUEING = "queueing"
    COMPLETION = "completion"

class MessageCache:
    """Caches message validation results"""

    def __init__(self, max_size: int = 1000):
        self.max_size = max_size
        self._cache: Dict[int, Dict[str, Any]] = {}
        self._access_times: Dict[int, datetime] = {}

    def add(self, message_id: int, result: Dict[str, Any]) -> None:
        """Add a result to cache"""
        if len(self._cache) >= self.max_size:
            self._cleanup_oldest()
        self._cache[message_id] = result
        self._access_times[message_id] = datetime.utcnow()

    def get(self, message_id: int) -> Optional[Dict[str, Any]]:
        """Get a cached result"""
        if message_id in self._cache:
            self._access_times[message_id] = datetime.utcnow()
            return self._cache[message_id]
        return None

    def _cleanup_oldest(self) -> None:
        """Remove oldest cache entries"""
        if not self._access_times:
            return
        oldest = min(self._access_times.items(), key=lambda x: x[1])[0]
        del self._cache[oldest]
        del self._access_times[oldest]

class ProcessingTracker:
    """Tracks message processing state and progress"""

    def __init__(self):
        self.states: Dict[int, MessageState] = {}
        self.stages: Dict[int, ProcessingStage] = {}
        self.errors: Dict[int, str] = {}
        self.start_times: Dict[int, datetime] = {}
        self.end_times: Dict[int, datetime] = {}

    def start_processing(self, message_id: int) -> None:
        """Start tracking a message"""
        self.states[message_id] = MessageState.RECEIVED
        self.start_times[message_id] = datetime.utcnow()

    def update_state(
        self,
        message_id: int,
        state: MessageState,
        stage: Optional[ProcessingStage] = None,
        error: Optional[str] = None
    ) -> None:
        """Update message state"""
        self.states[message_id] = state
        if stage:
            self.stages[message_id] = stage
        if error:
            self.errors[message_id] = error
        if state in (MessageState.COMPLETED, MessageState.FAILED, MessageState.IGNORED):
            self.end_times[message_id] = datetime.utcnow()

    def get_status(self, message_id: int) -> Dict[str, Any]:
        """Get processing status for a message"""
        return {
            "state": self.states.get(message_id),
            "stage": self.stages.get(message_id),
            "error": self.errors.get(message_id),
            "start_time": self.start_times.get(message_id),
            "end_time": self.end_times.get(message_id),
            "duration": (
                (self.end_times[message_id] - self.start_times[message_id]).total_seconds()
                if message_id in self.end_times and message_id in self.start_times
                else None
            )
        }

class MessageHandler:
    """Handles processing of messages for video content"""

    def __init__(self, bot, config_manager, queue_manager):
        self.bot = bot
        self.config_manager = config_manager
        self.url_extractor = URLExtractor()
        self.message_validator = MessageValidator()
        self.queue_processor = QueueProcessor(queue_manager)
        
        # Initialize tracking and caching
        self.tracker = ProcessingTracker()
        self.validation_cache = MessageCache()
        self._processing_lock = asyncio.Lock()

    async def process_message(self, message: discord.Message) -> None:
        """Process a message for video content"""
        # Start tracking
        self.tracker.start_processing(message.id)

        try:
            async with self._processing_lock:
                await self._process_message_internal(message)
        except Exception as e:
            logger.error(f"Error processing message: {str(e)}", exc_info=True)
            self.tracker.update_state(
                message.id,
                MessageState.FAILED,
                error=str(e)
            )
            try:
                await message.add_reaction(REACTIONS["error"])
            except:
                pass

    async def _process_message_internal(self, message: discord.Message) -> None:
        """Internal message processing logic"""
        try:
            # Get guild settings
            settings = await self.config_manager.get_guild_settings(message.guild.id)
            if not settings:
                logger.warning(f"No settings found for guild {message.guild.id}")
                self.tracker.update_state(message.id, MessageState.IGNORED)
                return

            # Check cache for validation
            cached_validation = self.validation_cache.get(message.id)
            if cached_validation:
                is_valid = cached_validation["valid"]
                reason = cached_validation["reason"]
            else:
                # Validate message
                self.tracker.update_state(
                    message.id,
                    MessageState.VALIDATING,
                    ProcessingStage.VALIDATION
                )
                is_valid, reason = await self.message_validator.validate_message(
                    message,
                    settings
                )
                # Cache result
                self.validation_cache.add(message.id, {
                    "valid": is_valid,
                    "reason": reason
                })

            if not is_valid:
                logger.debug(f"Message validation failed: {reason}")
                self.tracker.update_state(
                    message.id,
                    MessageState.IGNORED,
                    error=reason
                )
                return

            # Extract URLs
            self.tracker.update_state(
                message.id,
                MessageState.EXTRACTING,
                ProcessingStage.EXTRACTION
            )
            urls = await self.url_extractor.extract_urls(
                message,
                enabled_sites=settings.get("enabled_sites")
            )
            if not urls:
                logger.debug("No valid URLs found in message")
                self.tracker.update_state(message.id, MessageState.IGNORED)
                return

            # Process URLs
            self.tracker.update_state(
                message.id,
                MessageState.PROCESSING,
                ProcessingStage.QUEUEING
            )
            await self.queue_processor.process_urls(message, urls)

            # Mark completion
            self.tracker.update_state(
                message.id,
                MessageState.COMPLETED,
                ProcessingStage.COMPLETION
            )

        except Exception as e:
            self.tracker.update_state(
                message.id,
                MessageState.FAILED,
                error=str(e)
            )
            raise

    async def format_archive_message(
        self,
        author: Optional[discord.Member],
        channel: discord.TextChannel,
        url: str
    ) -> str:
        """Format message for archive channel"""
        return await self.queue_processor.format_archive_message(
            author,
            channel,
            url
        )

    def get_message_status(self, message_id: int) -> Dict[str, Any]:
        """Get processing status for a message"""
        return self.tracker.get_status(message_id)

    def is_healthy(self) -> bool:
        """Check if handler is healthy"""
        # Check for any stuck messages
        current_time = datetime.utcnow()
        for message_id, start_time in self.tracker.start_times.items():
            if (
                message_id in self.tracker.states and
                self.tracker.states[message_id] not in (
                    MessageState.COMPLETED,
                    MessageState.FAILED,
                    MessageState.IGNORED
                ) and
                (current_time - start_time).total_seconds() > 300  # 5 minutes timeout
            ):
                return False
        return True
