"""Module for handling command responses"""

import logging
import discord
from redbot.core.commands import Context

logger = logging.getLogger("VideoArchiver")

async def handle_response(ctx: Context, content: str = None, embed: discord.Embed = None) -> None:
    """Helper method to handle responses for both regular commands and interactions"""
    try:
        # Check if this is a slash command interaction
        is_interaction = hasattr(ctx, "interaction") and ctx.interaction is not None

        if is_interaction:
            try:
                # For slash commands
                if not ctx.interaction.response.is_done():
                    # If not responded yet, send initial response
                    if embed:
                        await ctx.interaction.response.send_message(
                            content=content, embed=embed
                        )
                    else:
                        await ctx.interaction.response.send_message(content=content)
                else:
                    # If already responded (deferred), use followup
                    try:
                        if embed:
                            await ctx.interaction.followup.send(
                                content=content, embed=embed
                            )
                        else:
                            await ctx.interaction.followup.send(content=content)
                    except AttributeError:
                        # Fallback if followup is not available
                        if embed:
                            await ctx.send(content=content, embed=embed)
                        else:
                            await ctx.send(content=content)
            except discord.errors.InteractionResponded:
                # If interaction was already responded to, try followup
                try:
                    if embed:
                        await ctx.interaction.followup.send(
                            content=content, embed=embed
                        )
                    else:
                        await ctx.interaction.followup.send(content=content)
                except (AttributeError, discord.errors.HTTPException):
                    # Final fallback to regular message
                    if embed:
                        await ctx.send(content=content, embed=embed)
                    else:
                        await ctx.send(content=content)
            except Exception as e:
                logger.error(f"Error handling interaction response: {e}")
                # Fallback to regular message
                if embed:
                    await ctx.send(content=content, embed=embed)
                else:
                    await ctx.send(content=content)
        else:
            # Regular command response
            if embed:
                await ctx.send(content=content, embed=embed)
            else:
                await ctx.send(content=content)
    except Exception as e:
        logger.error(f"Error sending response: {e}")
        # Final fallback attempt
        try:
            if embed:
                await ctx.send(content=content, embed=embed)
            else:
                await ctx.send(content=content)
        except Exception as e2:
            logger.error(f"Failed to send fallback message: {e2}")
