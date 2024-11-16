"""Module for handling command errors"""

import logging
import traceback
from redbot.core.commands import Context, MissingPermissions, BotMissingPermissions, MissingRequiredArgument, BadArgument
from ..utils.exceptions import VideoArchiverError as ProcessingError, ConfigurationError as ConfigError
from .response_handler import handle_response

logger = logging.getLogger("VideoArchiver")

async def handle_command_error(ctx: Context, error: Exception) -> None:
    """Handle command errors"""
    error_msg = None
    try:
        if isinstance(error, MissingPermissions):
            error_msg = "❌ You don't have permission to use this command."
        elif isinstance(error, BotMissingPermissions):
            error_msg = "❌ I don't have the required permissions to do that."
        elif isinstance(error, MissingRequiredArgument):
            error_msg = f"❌ Missing required argument: {error.param.name}"
        elif isinstance(error, BadArgument):
            error_msg = f"❌ Invalid argument: {str(error)}"
        elif isinstance(error, ConfigError):
            error_msg = f"❌ Configuration error: {str(error)}"
        elif isinstance(error, ProcessingError):
            error_msg = f"❌ Processing error: {str(error)}"
        else:
            logger.error(
                f"Command error in {ctx.command}: {traceback.format_exc()}"
            )
            error_msg = (
                "❌ An unexpected error occurred. Check the logs for details."
            )

        if error_msg:
            await handle_response(ctx, error_msg)

    except Exception as e:
        logger.error(f"Error handling command error: {str(e)}")
        try:
            await handle_response(
                ctx,
                "❌ An error occurred while handling another error. Please check the logs.",
            )
        except Exception:
            pass
