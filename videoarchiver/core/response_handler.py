"""Module for handling command responses"""

import logging
import discord
from typing import Optional, Union, Dict, Any
from redbot.core.commands import Context

logger = logging.getLogger("VideoArchiver")

class ResponseFormatter:
    """Formats responses for consistency"""

    @staticmethod
    def format_success(message: str) -> Dict[str, Any]:
        """Format a success message"""
        return {
            "content": f"✅ {message}",
            "color": discord.Color.green()
        }

    @staticmethod
    def format_error(message: str) -> Dict[str, Any]:
        """Format an error message"""
        return {
            "content": f"❌ {message}",
            "color": discord.Color.red()
        }

    @staticmethod
    def format_warning(message: str) -> Dict[str, Any]:
        """Format a warning message"""
        return {
            "content": f"⚠️ {message}",
            "color": discord.Color.yellow()
        }

    @staticmethod
    def format_info(message: str) -> Dict[str, Any]:
        """Format an info message"""
        return {
            "content": f"ℹ️ {message}",
            "color": discord.Color.blue()
        }

class InteractionHandler:
    """Handles slash command interactions"""

    @staticmethod
    async def send_initial_response(
        interaction: discord.Interaction,
        content: Optional[str] = None,
        embed: Optional[discord.Embed] = None
    ) -> bool:
        """Send initial interaction response"""
        try:
            if not interaction.response.is_done():
                if embed:
                    await interaction.response.send_message(content=content, embed=embed)
                else:
                    await interaction.response.send_message(content=content)
                return True
            return False
        except Exception as e:
            logger.error(f"Error sending initial interaction response: {e}")
            return False

    @staticmethod
    async def send_followup(
        interaction: discord.Interaction,
        content: Optional[str] = None,
        embed: Optional[discord.Embed] = None
    ) -> bool:
        """Send interaction followup"""
        try:
            if embed:
                await interaction.followup.send(content=content, embed=embed)
            else:
                await interaction.followup.send(content=content)
            return True
        except Exception as e:
            logger.error(f"Error sending interaction followup: {e}")
            return False

class ResponseManager:
    """Manages command responses"""

    def __init__(self):
        self.formatter = ResponseFormatter()
        self.interaction_handler = InteractionHandler()

    async def send_response(
        self,
        ctx: Context,
        content: Optional[str] = None,
        embed: Optional[discord.Embed] = None,
        response_type: str = "normal"
    ) -> None:
        """Send a response to a command
        
        Args:
            ctx: Command context
            content: Optional message content
            embed: Optional embed
            response_type: Type of response (normal, success, error, warning, info)
        """
        try:
            # Format response if type specified
            if response_type != "normal":
                format_method = getattr(self.formatter, f"format_{response_type}", None)
                if format_method and content:
                    formatted = format_method(content)
                    content = formatted["content"]
                    if not embed:
                        embed = discord.Embed(color=formatted["color"])

            # Handle response
            if self._is_interaction(ctx):
                await self._handle_interaction_response(ctx, content, embed)
            else:
                await self._handle_regular_response(ctx, content, embed)

        except Exception as e:
            logger.error(f"Error sending response: {e}")
            await self._send_fallback_response(ctx, content, embed)

    def _is_interaction(self, ctx: Context) -> bool:
        """Check if context is from an interaction"""
        return hasattr(ctx, "interaction") and ctx.interaction is not None

    async def _handle_interaction_response(
        self,
        ctx: Context,
        content: Optional[str],
        embed: Optional[discord.Embed]
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
            logger.error(f"Error handling interaction response: {e}")
            await self._send_fallback_response(ctx, content, embed)

    async def _handle_regular_response(
        self,
        ctx: Context,
        content: Optional[str],
        embed: Optional[discord.Embed]
    ) -> None:
        """Handle regular command response"""
        try:
            if embed:
                await ctx.send(content=content, embed=embed)
            else:
                await ctx.send(content=content)
        except Exception as e:
            logger.error(f"Error sending regular response: {e}")
            await self._send_fallback_response(ctx, content, embed)

    async def _send_fallback_response(
        self,
        ctx: Context,
        content: Optional[str],
        embed: Optional[discord.Embed]
    ) -> None:
        """Send fallback response when other methods fail"""
        try:
            if embed:
                await ctx.send(content=content, embed=embed)
            else:
                await ctx.send(content=content)
        except Exception as e:
            logger.error(f"Failed to send fallback response: {e}")

# Global response manager instance
response_manager = ResponseManager()

async def handle_response(
    ctx: Context,
    content: Optional[str] = None,
    embed: Optional[discord.Embed] = None,
    response_type: str = "normal"
) -> None:
    """Helper function to handle responses using the response manager"""
    await response_manager.send_response(ctx, content, embed, response_type)
