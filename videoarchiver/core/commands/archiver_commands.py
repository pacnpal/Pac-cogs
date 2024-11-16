"""Module for core archiver commands"""

import discord
from redbot.core.commands import Context, hybrid_group, guild_only
from redbot.core.utils.mod import admin_or_permissions
from discord import app_commands
import logging
from ..response_handler import handle_response

logger = logging.getLogger("VideoArchiver")

def setup_archiver_commands(cog):
    """Set up archiver commands for the cog"""
    
    @cog.hybrid_group(name="archiver", fallback="help")
    @guild_only()
    async def archiver(ctx: Context):
        """Manage video archiver settings."""
        if ctx.invoked_subcommand is None:
            await handle_response(
                ctx, "Use `/help archiver` for a list of commands."
            )

    @archiver.command(name="enable")
    @guild_only()
    @admin_or_permissions(administrator=True)
    async def enable_archiver(ctx: Context):
        """Enable video archiving in this server."""
        try:
            current_setting = await cog.config_manager.get_setting(
                ctx.guild.id, "enabled"
            )
            if current_setting:
                await handle_response(ctx, "Video archiving is already enabled.")
                return

            await cog.config_manager.update_setting(ctx.guild.id, "enabled", True)
            await handle_response(ctx, "Video archiving has been enabled.")

        except Exception as e:
            logger.error(f"Error enabling archiver: {e}")
            await handle_response(
                ctx, "An error occurred while enabling video archiving."
            )

    @archiver.command(name="disable")
    @guild_only()
    @admin_or_permissions(administrator=True)
    async def disable_archiver(ctx: Context):
        """Disable video archiving in this server."""
        try:
            current_setting = await cog.config_manager.get_setting(
                ctx.guild.id, "enabled"
            )
            if not current_setting:
                await handle_response(ctx, "Video archiving is already disabled.")
                return

            await cog.config_manager.update_setting(ctx.guild.id, "enabled", False)
            await handle_response(ctx, "Video archiving has been disabled.")

        except Exception as e:
            logger.error(f"Error disabling archiver: {e}")
            await handle_response(
                ctx, "An error occurred while disabling video archiving."
            )

    @archiver.command(name="queue")
    @guild_only()
    async def show_queue(ctx: Context):
        """Show the current video processing queue."""
        # Defer the response immediately for slash commands
        if hasattr(ctx, "interaction") and ctx.interaction:
            await ctx.defer()
        await cog.processor.show_queue_details(ctx)

    # Store commands in cog for access
    cog.archiver = archiver
    cog.enable_archiver = enable_archiver
    cog.disable_archiver = disable_archiver
    cog.show_queue = show_queue

    return archiver
