"""Module for handling command errors"""

import logging
import traceback
from typing import Dict, Optional, Tuple, Type, TypedDict, ClassVar
from enum import Enum, auto
import discord # type: ignore
from redbot.core.commands import ( # type: ignore
    Context,
    MissingPermissions,
    BotMissingPermissions,
    MissingRequiredArgument,
    BadArgument,
    CommandError
)

from ..utils.exceptions import (
    VideoArchiverError,
    ErrorSeverity,
    ErrorContext,
    ProcessorError,
    ValidationError,
    DisplayError,
    URLExtractionError,
    MessageHandlerError,
    QueueHandlerError,
    QueueProcessorError,
    FFmpegError,
    DatabaseError,
    HealthCheckError,
    TrackingError,
    NetworkError,
    ResourceExhaustedError,
    ConfigurationError
)
from ..core.response_handler import response_manager

logger = logging.getLogger("VideoArchiver")

class ErrorCategory(Enum):
    """Categories of errors"""
    PERMISSION = auto()
    ARGUMENT = auto()
    CONFIGURATION = auto()
    PROCESSING = auto()
    NETWORK = auto()
    RESOURCE = auto()
    DATABASE = auto()
    VALIDATION = auto()
    QUEUE = auto()
    CLEANUP = auto()
    HEALTH = auto()
    UNEXPECTED = auto()

class ErrorStats(TypedDict):
    """Type definition for error statistics"""
    counts: Dict[str, int]
    patterns: Dict[str, Dict[str, int]]
    severities: Dict[str, Dict[str, int]]

class ErrorFormatter:
    """Formats error messages for display"""

    @staticmethod
    def format_error_message(error: Exception, context: Optional[ErrorContext] = None) -> str:
        """Format error message with context"""
        base_message = str(error)
        if context:
            return f"{context}: {base_message}"
        return base_message

    @staticmethod
    def format_user_message(error: Exception, category: ErrorCategory) -> str:
        """Format user-friendly error message"""
        if isinstance(error, MissingPermissions):
            return "You don't have permission to use this command."
        elif isinstance(error, BotMissingPermissions):
            return "I don't have the required permissions to do that."
        elif isinstance(error, MissingRequiredArgument):
            return f"Missing required argument: {error.param.name}"
        elif isinstance(error, BadArgument):
            return f"Invalid argument: {str(error)}"
        elif isinstance(error, VideoArchiverError):
            return str(error)
        elif category == ErrorCategory.UNEXPECTED:
            return "An unexpected error occurred. Please check the logs for details."
        return str(error)

class ErrorCategorizer:
    """Categorizes errors and determines handling strategy"""

    ERROR_MAPPING: ClassVar[Dict[Type[Exception], Tuple[ErrorCategory, ErrorSeverity]]] = {
        # Discord command errors
        MissingPermissions: (ErrorCategory.PERMISSION, ErrorSeverity.MEDIUM),
        BotMissingPermissions: (ErrorCategory.PERMISSION, ErrorSeverity.HIGH),
        MissingRequiredArgument: (ErrorCategory.ARGUMENT, ErrorSeverity.LOW),
        BadArgument: (ErrorCategory.ARGUMENT, ErrorSeverity.LOW),
        
        # VideoArchiver errors
        ProcessorError: (ErrorCategory.PROCESSING, ErrorSeverity.HIGH),
        ValidationError: (ErrorCategory.VALIDATION, ErrorSeverity.MEDIUM),
        DisplayError: (ErrorCategory.PROCESSING, ErrorSeverity.LOW),
        URLExtractionError: (ErrorCategory.PROCESSING, ErrorSeverity.MEDIUM),
        MessageHandlerError: (ErrorCategory.PROCESSING, ErrorSeverity.MEDIUM),
        QueueHandlerError: (ErrorCategory.QUEUE, ErrorSeverity.HIGH),
        QueueProcessorError: (ErrorCategory.QUEUE, ErrorSeverity.HIGH),
        FFmpegError: (ErrorCategory.PROCESSING, ErrorSeverity.HIGH),
        DatabaseError: (ErrorCategory.DATABASE, ErrorSeverity.HIGH),
        HealthCheckError: (ErrorCategory.HEALTH, ErrorSeverity.HIGH),
        TrackingError: (ErrorCategory.PROCESSING, ErrorSeverity.MEDIUM),
        NetworkError: (ErrorCategory.NETWORK, ErrorSeverity.MEDIUM),
        ResourceExhaustedError: (ErrorCategory.RESOURCE, ErrorSeverity.HIGH),
        ConfigurationError: (ErrorCategory.CONFIGURATION, ErrorSeverity.HIGH)
    }

    @classmethod
    def categorize_error(cls, error: Exception) -> Tuple[ErrorCategory, ErrorSeverity]:
        """
        Categorize an error and determine its severity.
        
        Args:
            error: Exception to categorize
            
        Returns:
            Tuple of (Error category, Severity level)
        """
        for error_type, (category, severity) in cls.ERROR_MAPPING.items():
            if isinstance(error, error_type):
                return category, severity
        return ErrorCategory.UNEXPECTED, ErrorSeverity.HIGH

class ErrorTracker:
    """Tracks error occurrences and patterns"""

    def __init__(self) -> None:
        self.error_counts: Dict[str, int] = {}
        self.error_patterns: Dict[str, Dict[str, int]] = {}
        self.error_severities: Dict[str, Dict[str, int]] = {}

    def track_error(
        self,
        error: Exception,
        category: ErrorCategory,
        severity: ErrorSeverity
    ) -> None:
        """
        Track an error occurrence.
        
        Args:
            error: Exception that occurred
            category: Error category
            severity: Error severity
        """
        error_type = type(error).__name__
        
        # Track error counts
        self.error_counts[error_type] = self.error_counts.get(error_type, 0) + 1
        
        # Track error patterns by category
        if category.value not in self.error_patterns:
            self.error_patterns[category.value] = {}
        self.error_patterns[category.value][error_type] = (
            self.error_patterns[category.value].get(error_type, 0) + 1
        )
        
        # Track error severities
        if severity.value not in self.error_severities:
            self.error_severities[severity.value] = {}
        self.error_severities[severity.value][error_type] = (
            self.error_severities[severity.value].get(error_type, 0) + 1
        )

    def get_error_stats(self) -> ErrorStats:
        """
        Get error statistics.
        
        Returns:
            Dictionary containing error statistics
        """
        return ErrorStats(
            counts=self.error_counts.copy(),
            patterns=self.error_patterns.copy(),
            severities=self.error_severities.copy()
        )

class ErrorManager:
    """Manages error handling and reporting"""

    def __init__(self) -> None:
        self.formatter = ErrorFormatter()
        self.categorizer = ErrorCategorizer()
        self.tracker = ErrorTracker()

    async def handle_error(
        self,
        ctx: Context,
        error: Exception
    ) -> None:
        """
        Handle a command error.
        
        Args:
            ctx: Command context
            error: The error that occurred
        """
        try:
            # Categorize error
            category, severity = self.categorizer.categorize_error(error)
            
            # Create error context
            context = ErrorContext(
                component=ctx.command.qualified_name if ctx.command else "unknown",
                operation="command_execution",
                details={
                    "guild_id": str(ctx.guild.id) if ctx.guild else "DM",
                    "channel_id": str(ctx.channel.id),
                    "user_id": str(ctx.author.id)
                },
                severity=severity
            )
            
            # Track error
            self.tracker.track_error(error, category, severity)
            
            # Format error messages
            log_message = self.formatter.format_error_message(error, context)
            user_message = self.formatter.format_user_message(error, category)
            
            # Log error details
            self._log_error(log_message, severity)
            
            # Send response
            await response_manager.send_response(
                ctx,
                content=user_message,
                response_type=severity.name.lower()
            )

        except Exception as e:
            logger.error(
                f"Error handling command error: {str(e)}\n"
                f"Original error: {traceback.format_exc()}"
            )
            try:
                await response_manager.send_response(
                    ctx,
                    content="An error occurred while handling another error. Please check the logs.",
                    response_type="error"
                )
            except Exception:
                pass

    def _log_error(
        self,
        message: str,
        severity: ErrorSeverity
    ) -> None:
        """
        Log error details.
        
        Args:
            message: Error message to log
            severity: Error severity
        """
        try:
            if severity in (ErrorSeverity.HIGH, ErrorSeverity.CRITICAL):
                logger.error(f"{message}\n{traceback.format_exc()}")
            elif severity == ErrorSeverity.MEDIUM:
                logger.warning(message)
            else:
                logger.info(message)
        except Exception as e:
            logger.error(f"Error logging error details: {e}")

# Global error manager instance
error_manager = ErrorManager()

async def handle_command_error(ctx: Context, error: Exception) -> None:
    """
    Helper function to handle command errors using the error manager.
    
    Args:
        ctx: Command context
        error: Exception to handle
    """
    await error_manager.handle_error(ctx, error)
