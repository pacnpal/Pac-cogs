"""Message processing and URL extraction for VideoProcessor"""

import asyncio
import logging
from datetime import datetime, timedelta
from enum import auto, Enum
from typing import Any, ClassVar, Dict, List, Optional, Set, Tuple, TypedDict, TYPE_CHECKING

import discord  # type: ignore
from discord.ext import commands  # type: ignore

from ..config_manager import ConfigManager
from ..processor.constants import REACTIONS
from ..processor.message_validator import MessageValidator, ValidationError
from ..processor.url_extractor import URLExtractor, URLMetadata
from ..queue.types import QueuePriority
from ..utils.exceptions import MessageHandlerError

if TYPE_CHECKING:
    from ..queue.manager import EnhancedVideoQueueManager

logger = logging.getLogger("VideoArchiver")


class MessageState(Enum):
    """Possible states of message processing"""

    RECEIVED = auto()
    VALIDATING = auto()
    EXTRACTING = auto()
    PROCESSING = auto()
    COMPLETED = auto()
    FAILED = auto()
    IGNORED = auto()


class ProcessingStage(Enum):
    """Message processing stages"""

    VALIDATION = auto()
    EXTRACTION = auto()
    QUEUEING = auto()
    COMPLETION = auto()


class MessageCacheEntry(TypedDict):
    """Type definition for message cache entry"""

    valid: bool
    reason: Optional[str]
    timestamp: str


class MessageStatus(TypedDict):
    """Type definition for message status"""

    state: Optional[MessageState]
    stage: Optional[ProcessingStage]
    error: Optional[str]
    start_time: Optional[datetime]
    end_time: Optional[datetime]
    duration: Optional[float]


class MessageCache:
    """Caches message validation results"""

    def __init__(self, max_size: int = 1000) -> None:
        self.max_size = max_size
        self._cache: Dict[int, MessageCacheEntry] = {}
        self._access_times: Dict[int, datetime] = {}

    def add(self, message_id: int, result: MessageCacheEntry) -> None:
        """
        Add a result to cache.

        Args:
            message_id: Discord message ID
            result: Validation result entry
        """
        if len(self._cache) >= self.max_size:
            self._cleanup_oldest()
        self._cache[message_id] = result
        self._access_times[message_id] = datetime.utcnow()

    def get(self, message_id: int) -> Optional[MessageCacheEntry]:
        """
        Get a cached result.

        Args:
            message_id: Discord message ID

        Returns:
            Cached validation entry or None if not found
        """
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

    MAX_PROCESSING_TIME: ClassVar[int] = 300  # 5 minutes in seconds

    def __init__(self) -> None:
        self.states: Dict[int, MessageState] = {}
        self.stages: Dict[int, ProcessingStage] = {}
        self.errors: Dict[int, str] = {}
        self.start_times: Dict[int, datetime] = {}
        self.end_times: Dict[int, datetime] = {}

    def start_processing(self, message_id: int) -> None:
        """
        Start tracking a message.

        Args:
            message_id: Discord message ID
        """
        self.states[message_id] = MessageState.RECEIVED
        self.start_times[message_id] = datetime.utcnow()

    def update_state(
        self,
        message_id: int,
        state: MessageState,
        stage: Optional[ProcessingStage] = None,
        error: Optional[str] = None,
    ) -> None:
        """
        Update message state.

        Args:
            message_id: Discord message ID
            state: New message state
            stage: Optional processing stage
            error: Optional error message
        """
        self.states[message_id] = state
        if stage:
            self.stages[message_id] = stage
        if error:
            self.errors[message_id] = error
        if state in (MessageState.COMPLETED, MessageState.FAILED, MessageState.IGNORED):
            self.end_times[message_id] = datetime.utcnow()

    def get_status(self, message_id: int) -> MessageStatus:
        """
        Get processing status for a message.

        Args:
            message_id: Discord message ID

        Returns:
            Dictionary containing message status information
        """
        end_time = self.end_times.get(message_id)
        start_time = self.start_times.get(message_id)

        return MessageStatus(
            state=self.states.get(message_id),
            stage=self.stages.get(message_id),
            error=self.errors.get(message_id),
            start_time=start_time,
            end_time=end_time,
            duration=(
                (end_time - start_time).total_seconds()
                if end_time and start_time
                else None
            ),
        )

    def is_message_stuck(self, message_id: int) -> bool:
        """
        Check if a message is stuck in processing.

        Args:
            message_id: Discord message ID

        Returns:
            True if message is stuck, False otherwise
        """
        if message_id not in self.states or message_id not in self.start_times:
            return False

        state = self.states[message_id]
        if state in (MessageState.COMPLETED, MessageState.FAILED, MessageState.IGNORED):
            return False

        processing_time = (
            datetime.utcnow() - self.start_times[message_id]
        ).total_seconds()
        return processing_time > self.MAX_PROCESSING_TIME


class MessageHandler:
    """Handles processing of messages for video content"""

    def __init__(
        self,
        bot: discord.Client,
        config_manager: ConfigManager,
        queue_manager: "EnhancedVideoQueueManager",
    ) -> None:
        self.bot = bot
        self.config_manager = config_manager
        self.url_extractor = URLExtractor()
        self.message_validator = MessageValidator()
        self.queue_manager = queue_manager

        # Initialize tracking and caching
        self.tracker = ProcessingTracker()
        self.validation_cache = MessageCache()
        self._processing_lock = asyncio.Lock()

    async def process_message(self, message: discord.Message) -> None:
        """
        Process a message for video content.

        Args:
            message: Discord message to process

        Raises:
            MessageHandlerError: If there's an error during processing
        """
        # Start tracking
        self.tracker.start_processing(message.id)

        try:
            async with self._processing_lock:
                await self._process_message_internal(message)
        except Exception as e:
            logger.error(f"Error processing message: {str(e)}", exc_info=True)
            self.tracker.update_state(message.id, MessageState.FAILED, error=str(e))
            try:
                await message.add_reaction(REACTIONS["error"])
            except Exception as react_error:
                logger.error(f"Failed to add error reaction: {react_error}")

    async def _process_message_internal(self, message: discord.Message) -> None:
        """
        Internal message processing logic.

        Args:
            message: Discord message to process

        Raises:
            MessageHandlerError: If there's an error during processing
        """
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
                    message.id, MessageState.VALIDATING, ProcessingStage.VALIDATION
                )
                try:
                    is_valid, reason = await self.message_validator.validate_message(
                        message, settings
                    )
                    # Cache result
                    self.validation_cache.add(
                        message.id,
                        MessageCacheEntry(
                            valid=is_valid,
                            reason=reason,
                            timestamp=datetime.utcnow().isoformat(),
                        ),
                    )
                except ValidationError as e:
                    raise MessageHandlerError(f"Validation failed: {str(e)}")

            if not is_valid:
                logger.debug(f"Message validation failed: {reason}")
                self.tracker.update_state(
                    message.id, MessageState.IGNORED, error=reason
                )
                return

            # Extract URLs
            self.tracker.update_state(
                message.id, MessageState.EXTRACTING, ProcessingStage.EXTRACTION
            )
            try:
                urls: List[URLMetadata] = await self.url_extractor.extract_urls(
                    message, enabled_sites=settings.get("enabled_sites")
                )
                if not urls:
                    logger.debug("No valid URLs found in message")
                    self.tracker.update_state(message.id, MessageState.IGNORED)
                    return
            except Exception as e:
                raise MessageHandlerError(f"URL extraction failed: {str(e)}")

            # Process URLs
            self.tracker.update_state(
                message.id, MessageState.PROCESSING, ProcessingStage.QUEUEING
            )
            try:
                for url_metadata in urls:
                    await self.queue_manager.add_to_queue(
                        url=url_metadata.url,
                        message_id=message.id,
                        channel_id=message.channel.id,
                        guild_id=message.guild.id,
                        author_id=message.author.id,
                        priority=QueuePriority.NORMAL.value
                    )
            except Exception as e:
                raise MessageHandlerError(f"Queue processing failed: {str(e)}")

            # Mark completion
            self.tracker.update_state(
                message.id, MessageState.COMPLETED, ProcessingStage.COMPLETION
            )

        except MessageHandlerError:
            raise
        except Exception as e:
            raise MessageHandlerError(f"Unexpected error: {str(e)}")

    def get_message_status(self, message_id: int) -> MessageStatus:
        """
        Get processing status for a message.

        Args:
            message_id: Discord message ID

        Returns:
            Dictionary containing message status information
        """
        return self.tracker.get_status(message_id)

    def is_healthy(self) -> bool:
        """
        Check if handler is healthy.

        Returns:
            True if handler is healthy, False otherwise
        """
        try:
            # Check for any stuck messages
            for message_id in self.tracker.states:
                if self.tracker.is_message_stuck(message_id):
                    logger.warning(
                        f"Message {message_id} appears to be stuck in processing"
                    )
                    return False
            return True
        except Exception as e:
            logger.error(f"Error checking health: {e}")
            return False
