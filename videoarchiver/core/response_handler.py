"""Module for handling command responses"""

import logging
from enum import Enum, auto
from typing import Optional, Union, Dict, Any, TypedDict, ClassVar
from datetime import datetime
import discord  # type: ignore
from redbot.core.commands import Context  # type: ignore

# try:
# Try relative imports first
from utils.exceptions import ErrorSeverity

# except ImportError:
# Fall back to absolute imports if relative imports fail
# from videoarchiver.utils.exceptions import ErrorSeverity

logger = logging.getLogger("VideoArchiver")


class ResponseType(Enum):
    """Types of responses"""

    NORMAL = auto()
    SUCCESS = auto()
    ERROR = auto()
    WARNING = auto()
    INFO = auto()
    DEBUG = auto()


class ResponseTheme(TypedDict):
    """Type definition for response theme"""

    emoji: str
    color: discord.Color


class ResponseFormat(TypedDict):
    """Type definition for formatted response"""

    content: str
    color: discord.Color
    timestamp: str


class ResponseFormatter:
    """Formats responses for consistency"""

    THEMES: ClassVar[Dict[ResponseType, ResponseTheme]] = {
        ResponseType.SUCCESS: ResponseTheme(emoji="✅", color=discord.Color.green()),
        ResponseType.ERROR: ResponseTheme(emoji="❌", color=discord.Color.red()),
        ResponseType.WARNING: ResponseTheme(emoji="⚠️", color=discord.Color.gold()),
        ResponseType.INFO: ResponseTheme(emoji="ℹ️", color=discord.Color.blue()),
        ResponseType.DEBUG: ResponseTheme(emoji="🔧", color=discord.Color.greyple()),
    }

    SEVERITY_MAPPING: ClassVar[Dict[ErrorSeverity, ResponseType]] = {
        ErrorSeverity.LOW: ResponseType.INFO,
        ErrorSeverity.MEDIUM: ResponseType.WARNING,
        ErrorSeverity.HIGH: ResponseType.ERROR,
        ErrorSeverity.CRITICAL: ResponseType.ERROR,
    }

    @classmethod
    def format_response(
        cls, message: str, response_type: ResponseType = ResponseType.NORMAL
    ) -> ResponseFormat:
        """
        Format a response message.

        Args:
            message: Message to format
            response_type: Type of response

        Returns:
            Formatted response dictionary
        """
        theme = cls.THEMES.get(response_type)
        if theme:
            return ResponseFormat(
                content=f"{theme['emoji']} {message}",
                color=theme["color"],
                timestamp=datetime.utcnow().isoformat(),
            )
        return ResponseFormat(
            content=message,
            color=discord.Color.default(),
            timestamp=datetime.utcnow().isoformat(),
        )

    @classmethod
    def get_response_type(cls, severity: ErrorSeverity) -> ResponseType:
        """
        Get response type for error severity.

        Args:
            severity: Error severity level

        Returns:
            Appropriate response type
        """
        return cls.SEVERITY_MAPPING.get(severity, ResponseType.ERROR)


class InteractionHandler:
    """Handles slash command interactions"""

    async def send_initial_response(
        self,
        interaction: discord.Interaction,
        content: Optional[str] = None,
        embed: Optional[discord.Embed] = None,
    ) -> bool:
        """
        Send initial interaction response.

        Args:
            interaction: Discord interaction
            content: Optional message content
            embed: Optional embed

        Returns:
            True if response was sent successfully
        """
        try:
            if not interaction.response.is_done():
                if embed:
                    await interaction.response.send_message(
                        content=content, embed=embed
                    )
                else:
                    await interaction.response.send_message(content=content)
                return True
            return False
        except Exception as e:
            logger.error(
                f"Error sending initial interaction response: {e}", exc_info=True
            )
            return False

    async def send_followup(
        self,
        interaction: discord.Interaction,
        content: Optional[str] = None,
        embed: Optional[discord.Embed] = None,
    ) -> bool:
        """
        Send interaction followup.

        Args:
            interaction: Discord interaction
            content: Optional message content
            embed: Optional embed

        Returns:
            True if followup was sent successfully
        """
        try:
            if embed:
                await interaction.followup.send(content=content, embed=embed)
            else:
                await interaction.followup.send(content=content)
            return True
        except Exception as e:
            logger.error(f"Error sending interaction followup: {e}", exc_info=True)
            return False


class ResponseManager:
    """Manages command responses"""

    def __init__(self) -> None:
        self.formatter = ResponseFormatter()
        self.interaction_handler = InteractionHandler()

    async def send_response(
        self,
        ctx: Context,
        content: Optional[str] = None,
        embed: Optional[discord.Embed] = None,
        response_type: Union[ResponseType, str, ErrorSeverity] = ResponseType.NORMAL,
    ) -> None:
        """
        Send a response to a command.

        Args:
            ctx: Command context
            content: Optional message content
            embed: Optional embed
            response_type: Type of response or error severity
        """
        try:
            # Convert string response type to enum
            if isinstance(response_type, str):
                try:
                    response_type = ResponseType[response_type.upper()]
                except KeyError:
                    response_type = ResponseType.NORMAL
            # Convert error severity to response type
            elif isinstance(response_type, ErrorSeverity):
                response_type = self.formatter.get_response_type(response_type)

            # Format response
            if response_type != ResponseType.NORMAL and content:
                formatted = self.formatter.format_response(content, response_type)
                content = formatted["content"]
                if not embed:
                    embed = discord.Embed(
                        color=formatted["color"],
                        timestamp=datetime.fromisoformat(formatted["timestamp"]),
                    )

            # Handle response
            if self._is_interaction(ctx):
                await self._handle_interaction_response(ctx, content, embed)
            else:
                await self._handle_regular_response(ctx, content, embed)

        except Exception as e:
            logger.error(f"Error sending response: {e}", exc_info=True)
            await self._send_fallback_response(ctx, content, embed)

    def _is_interaction(self, ctx: Context) -> bool:
        """Check if context is from an interaction"""
        return hasattr(ctx, "interaction") and ctx.interaction is not None

    async def _handle_interaction_response(
        self, ctx: Context, content: Optional[str], embed: Optional[discord.Embed]
    ) -> None:
        """Handle interaction response"""
        try:
            # Try initial response
            if await self.interaction_handler.send_initial_response(
                ctx.interaction, content, embed
            ):
                return

            # Try followup
            if await self.interaction_handler.send_followup(
                ctx.interaction, content, embed
            ):
                return

            # Fallback to regular message
            await self._handle_regular_response(ctx, content, embed)

        except Exception as e:
            logger.error(f"Error handling interaction response: {e}", exc_info=True)
            await self._send_fallback_response(ctx, content, embed)

    async def _handle_regular_response(
        self, ctx: Context, content: Optional[str], embed: Optional[discord.Embed]
    ) -> None:
        """Handle regular command response"""
        try:
            if embed:
                await ctx.send(content=content, embed=embed)
            else:
                await ctx.send(content=content)
        except Exception as e:
            logger.error(f"Error sending regular response: {e}", exc_info=True)
            await self._send_fallback_response(ctx, content, embed)

    async def _send_fallback_response(
        self, ctx: Context, content: Optional[str], embed: Optional[discord.Embed]
    ) -> None:
        """Send fallback response when other methods fail"""
        try:
            if embed:
                await ctx.send(content=content, embed=embed)
            else:
                await ctx.send(content=content)
        except Exception as e:
            logger.error(f"Failed to send fallback response: {e}", exc_info=True)


# Global response manager instance
response_manager = ResponseManager()


async def handle_response(
    ctx: Context,
    content: Optional[str] = None,
    embed: Optional[discord.Embed] = None,
    response_type: Union[ResponseType, str, ErrorSeverity] = ResponseType.NORMAL,
) -> None:
    """
    Helper function to handle responses using the response manager.

    Args:
        ctx: Command context
        content: Optional message content
        embed: Optional embed
        response_type: Type of response or error severity
    """
    await response_manager.send_response(ctx, content, embed, response_type)
