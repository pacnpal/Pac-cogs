"""Module for handling command errors"""

import logging
import traceback
from typing import Dict, Optional, Tuple, Type
import discord
from redbot.core.commands import (
    Context,
    MissingPermissions,
    BotMissingPermissions,
    MissingRequiredArgument,
    BadArgument,
    CommandError
)

from ..utils.exceptions import VideoArchiverError as ProcessingError, ConfigurationError as ConfigError
from .response_handler import response_manager

logger = logging.getLogger("VideoArchiver")

class ErrorFormatter:
    """Formats error messages for display"""

    @staticmethod
    def format_permission_error(error: Exception) -> str:
        """Format permission error messages"""
        if isinstance(error, MissingPermissions):
            return "You don't have permission to use this command."
        elif isinstance(error, BotMissingPermissions):
            return "I don't have the required permissions to do that."
        return str(error)

    @staticmethod
    def format_argument_error(error: Exception) -> str:
        """Format argument error messages"""
        if isinstance(error, MissingRequiredArgument):
            return f"Missing required argument: {error.param.name}"
        elif isinstance(error, BadArgument):
            return f"Invalid argument: {str(error)}"
        return str(error)

    @staticmethod
    def format_processing_error(error: ProcessingError) -> str:
        """Format processing error messages"""
        return f"Processing error: {str(error)}"

    @staticmethod
    def format_config_error(error: ConfigError) -> str:
        """Format configuration error messages"""
        return f"Configuration error: {str(error)}"

    @staticmethod
    def format_unexpected_error(error: Exception) -> str:
        """Format unexpected error messages"""
        return "An unexpected error occurred. Check the logs for details."

class ErrorCategorizer:
    """Categorizes errors and determines handling strategy"""

    ERROR_TYPES = {
        MissingPermissions: ("permission", "error"),
        BotMissingPermissions: ("permission", "error"),
        MissingRequiredArgument: ("argument", "warning"),
        BadArgument: ("argument", "warning"),
        ConfigError: ("configuration", "error"),
        ProcessingError: ("processing", "error"),
    }

    @classmethod
    def categorize_error(cls, error: Exception) -> Tuple[str, str]:
        """Categorize an error and determine its severity
        
        Returns:
            Tuple[str, str]: (Error category, Severity level)
        """
        for error_type, (category, severity) in cls.ERROR_TYPES.items():
            if isinstance(error, error_type):
                return category, severity
        return "unexpected", "error"

class ErrorTracker:
    """Tracks error occurrences and patterns"""

    def __init__(self):
        self.error_counts: Dict[str, int] = {}
        self.error_patterns: Dict[str, Dict[str, int]] = {}

    def track_error(self, error: Exception, category: str) -> None:
        """Track an error occurrence"""
        error_type = type(error).__name__
        self.error_counts[error_type] = self.error_counts.get(error_type, 0) + 1
        
        if category not in self.error_patterns:
            self.error_patterns[category] = {}
        self.error_patterns[category][error_type] = self.error_patterns[category].get(error_type, 0) + 1

    def get_error_stats(self) -> Dict:
        """Get error statistics"""
        return {
            "counts": self.error_counts.copy(),
            "patterns": self.error_patterns.copy()
        }

class ErrorManager:
    """Manages error handling and reporting"""

    def __init__(self):
        self.formatter = ErrorFormatter()
        self.categorizer = ErrorCategorizer()
        self.tracker = ErrorTracker()

    async def handle_error(
        self,
        ctx: Context,
        error: Exception
    ) -> None:
        """Handle a command error
        
        Args:
            ctx: Command context
            error: The error that occurred
        """
        try:
            # Categorize error
            category, severity = self.categorizer.categorize_error(error)
            
            # Track error
            self.tracker.track_error(error, category)
            
            # Format error message
            error_msg = await self._format_error_message(error, category)
            
            # Log error details
            self._log_error(ctx, error, category, severity)
            
            # Send response
            await response_manager.send_response(
                ctx,
                content=error_msg,
                response_type=severity
            )

        except Exception as e:
            logger.error(f"Error handling command error: {str(e)}")
            try:
                await response_manager.send_response(
                    ctx,
                    content="An error occurred while handling another error. Please check the logs.",
                    response_type="error"
                )
            except Exception:
                pass

    async def _format_error_message(
        self,
        error: Exception,
        category: str
    ) -> str:
        """Format error message based on category"""
        try:
            if category == "permission":
                return self.formatter.format_permission_error(error)
            elif category == "argument":
                return self.formatter.format_argument_error(error)
            elif category == "processing":
                return self.formatter.format_processing_error(error)
            elif category == "configuration":
                return self.formatter.format_config_error(error)
            else:
                return self.formatter.format_unexpected_error(error)
        except Exception as e:
            logger.error(f"Error formatting error message: {e}")
            return "An error occurred. Please check the logs."

    def _log_error(
        self,
        ctx: Context,
        error: Exception,
        category: str,
        severity: str
    ) -> None:
        """Log error details"""
        try:
            if severity == "error":
                logger.error(
                    f"Command error in {ctx.command} (Category: {category}):\n"
                    f"{traceback.format_exc()}"
                )
            else:
                logger.warning(
                    f"Command warning in {ctx.command} (Category: {category}):\n"
                    f"{str(error)}"
                )
        except Exception as e:
            logger.error(f"Error logging error details: {e}")

# Global error manager instance
error_manager = ErrorManager()

async def handle_command_error(ctx: Context, error: Exception) -> None:
    """Helper function to handle command errors using the error manager"""
    await error_manager.handle_error(ctx, error)
