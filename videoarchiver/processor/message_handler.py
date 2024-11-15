"""Message processing and URL extraction for VideoProcessor"""

import logging
import discord
from typing import List, Tuple, Optional
from videoarchiver.utils.video_downloader import is_video_url_pattern
from .reactions import REACTIONS

logger = logging.getLogger("VideoArchiver")

class MessageHandler:
    """Handles processing of messages for video content"""

    def __init__(self, bot, config_manager, queue_manager):
        self.bot = bot
        self.config_manager = config_manager
        self.queue_manager = queue_manager

    async def process_message(self, message: discord.Message) -> None:
        """Process a message for video content"""
        try:
            # Check if message contains any content to process
            if not message.content and not message.attachments:
                logger.debug(f"No content or attachments in message {message.id}")
                return

            # Get guild settings
            settings = await self.config_manager.get_guild_settings(message.guild.id)
            if not settings:
                logger.warning(f"No settings found for guild {message.guild.id}")
                return

            # Log settings for debugging
            logger.debug(f"Guild {message.guild.id} settings: {settings}")

            # Check if channel is enabled
            enabled_channels = settings.get("enabled_channels", [])
            if enabled_channels and message.channel.id not in enabled_channels:
                logger.debug(f"Channel {message.channel.id} not in enabled channels: {enabled_channels}")
                return

            # Extract URLs from message
            urls = await self._extract_urls(message, settings)
            if not urls:
                logger.debug("No valid URLs found in message")
                return

            # Process each URL
            await self._process_urls(message, urls)

        except Exception as e:
            logger.error(f"Error processing message: {str(e)}", exc_info=True)
            try:
                await message.add_reaction(REACTIONS["error"])
            except:
                pass

    async def _extract_urls(self, message: discord.Message, settings: dict) -> List[str]:
        """Extract video URLs from message content and attachments"""
        urls = []
        
        # Extract from message content
        if message.content:
            logger.debug(f"Processing message content: {message.content}")
            enabled_sites = settings.get("enabled_sites", [])
            logger.debug(f"Enabled sites: {enabled_sites}")

            for word in message.content.split():
                logger.debug(f"Checking word: {word}")
                if is_video_url_pattern(word):
                    if not enabled_sites or any(site in word.lower() for site in enabled_sites):
                        logger.debug(f"Found matching URL: {word}")
                        urls.append(word)
                    else:
                        logger.debug(f"URL {word} doesn't match any enabled sites")
                else:
                    logger.debug(f"Word {word} is not a valid video URL")

        # Extract from attachments
        for attachment in message.attachments:
            logger.debug(f"Checking attachment: {attachment.filename}")
            if any(attachment.filename.lower().endswith(ext) for ext in ['.mp4', '.mov', '.avi', '.webm']):
                logger.debug(f"Found video attachment: {attachment.url}")
                urls.append(attachment.url)

        return urls

    async def _process_urls(self, message: discord.Message, urls: List[str]) -> None:
        """Process extracted URLs by adding them to the queue"""
        for url in urls:
            try:
                logger.info(f"Adding URL to queue: {url}")
                await message.add_reaction(REACTIONS['queued'])
                await self.queue_manager.add_to_queue(
                    url=url,
                    message_id=message.id,
                    channel_id=message.channel.id,
                    guild_id=message.guild.id,
                    author_id=message.author.id,
                    priority=0
                )
                logger.info(f"Successfully added video to queue: {url}")
            except Exception as e:
                logger.error(f"Failed to add video to queue: {str(e)}")
                await message.add_reaction(REACTIONS['error'])
                continue

    async def format_archive_message(self, author: Optional[discord.Member], 
                                   channel: discord.TextChannel, 
                                   url: str) -> str:
        """Format message for archive channel"""
        author_mention = author.mention if author else "Unknown User"
        channel_mention = channel.mention if channel else "Unknown Channel"
        
        return (f"Video archived from {author_mention} in {channel_mention}\n"
                f"Original URL: {url}")
