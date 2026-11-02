"""URL extraction functionality for video processing"""

import functools
import logging
from enum import Enum
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Set
from datetime import datetime
import discord # type: ignore
import yt_dlp # type: ignore
from urllib.parse import urlparse, parse_qs, ParseResult

logger = logging.getLogger("VideoArchiver")

# Discord markup and punctuation around a link: <url> (no embed), ||url||, (url), "url.", ...
URL_WRAPPING_CHARS = "<>()[]|*`'\",.!?"

@dataclass
class URLMetadata:
    """Metadata about an extracted URL"""
    url: str
    site: str
    timestamp: Optional[int] = None
    playlist_id: Optional[str] = None
    video_id: Optional[str] = None
    quality: Optional[str] = None
    extraction_time: str = field(default_factory=lambda: datetime.utcnow().isoformat())

class URLType(Enum):
    """Types of video URLs"""
    DIRECT = "direct"
    PLATFORM = "platform"
    UNKNOWN = "unknown"


# Keyed on the module, so a yt-dlp hot-swapped by update_checker brings its new sites along
@functools.lru_cache(maxsize=1)
def _extractors(module) -> List[type]:
    """Every yt-dlp extractor that can hand back a single video, minus the catch-all Generic one"""
    # ponytail: "any" extractors (tweets, youtube:tab) stay in, since youtube:tab also serves
    # watch?v=...&list=...; a channel or playlist link there archives one video (playlist_items=1).
    return [
        ie for ie in module.extractor.gen_extractor_classes()
        if ie._ENABLED and ie.ie_key() != "Generic" and getattr(ie, "_RETURN_TYPE", None) != "playlist"
    ]


class URLPatternManager:
    """Recognises video URLs using yt-dlp's own extractors, so every site it supports counts"""

    def __init__(self) -> None:
        self.direct_extensions: Set[str] = {'.mp4', '.mov', '.avi', '.webm', '.mkv'}

    def find_extractor(self, url: str) -> Optional[type]:
        """The first yt-dlp extractor that accepts this URL, or None"""
        if not url.lower().startswith(("http://", "https://")):
            return None
        return next((ie for ie in _extractors(yt_dlp) if ie.suitable(url)), None)

    @staticmethod
    def site_name(extractor: type) -> str:
        """yt-dlp's name for the site: "youtube" for both youtube and youtube:tab"""
        return extractor.IE_NAME.split(":")[0].lower()

    def is_supported_site(self, url: str, site: str, enabled_sites: Optional[List[str]]) -> bool:
        """
        Check the URL against the guild's enabled sites.

        Args:
            url: URL to check
            site: yt-dlp site name for the URL ("direct" for file links)
            enabled_sites: Site names or domain fragments; empty means all

        Returns:
            True if site is enabled, False otherwise
        """
        if not enabled_sites:
            return True

        try:
            domain = urlparse(url.lower()).netloc.replace('www.', '')
            return any(s.lower() == site or s.lower() in domain for s in enabled_sites)
        except Exception as e:
            logger.error(f"Error checking site support for {url}: {e}")
            return False

class URLValidator:
    """Validates extracted URLs"""

    def __init__(self, pattern_manager: URLPatternManager) -> None:
        self.pattern_manager = pattern_manager

    def get_url_type(self, url: str) -> URLType:
        """
        Determine URL type.
        
        Args:
            url: URL to check
            
        Returns:
            URLType indicating the type of URL
        """
        try:
            parsed = urlparse(url)
            if any(parsed.path.lower().endswith(ext) for ext in self.pattern_manager.direct_extensions):
                return URLType.DIRECT
            if self.pattern_manager.find_extractor(url):
                return URLType.PLATFORM
            return URLType.UNKNOWN
        except Exception as e:
            logger.error(f"Error determining URL type for {url}: {e}")
            return URLType.UNKNOWN

    def is_valid_url(self, url: str) -> bool:
        """
        Validate URL format.
        
        Args:
            url: URL to validate
            
        Returns:
            True if URL is valid, False otherwise
        """
        try:
            result = urlparse(url)
            return all([result.scheme, result.netloc])
        except Exception as e:
            logger.error(f"Error validating URL {url}: {e}")
            return False

class URLMetadataExtractor:
    """Extracts metadata from URLs"""

    def __init__(self, pattern_manager: URLPatternManager) -> None:
        self.pattern_manager = pattern_manager

    def extract_metadata(self, url: str) -> Optional[URLMetadata]:
        """
        Extract metadata from URL.
        
        Args:
            url: URL to extract metadata from
            
        Returns:
            URLMetadata object or None if extraction fails
        """
        try:
            parsed = urlparse(url)
            
            # Handle direct video URLs
            if any(parsed.path.lower().endswith(ext) for ext in self.pattern_manager.direct_extensions):
                return URLMetadata(url=url, site="direct")

            # Handle platform URLs
            if ie := self.pattern_manager.find_extractor(url):
                return URLMetadata(
                    url=url,
                    site=self.pattern_manager.site_name(ie),
                    video_id=ie.get_temp_id(url),
                    timestamp=self._extract_timestamp(parsed),
                    playlist_id=self._extract_playlist_id(parsed),
                )

            return None

        except Exception as e:
            logger.error(f"Error extracting metadata from URL {url}: {e}", exc_info=True)
            return None

    def _extract_timestamp(self, parsed_url: ParseResult) -> Optional[int]:
        """Extract timestamp from URL"""
        try:
            params = parse_qs(parsed_url.query)
            if 't' in params:
                return int(params['t'][0])
            return None
        except (ValueError, IndexError) as e:
            logger.debug(f"Error extracting timestamp: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error extracting timestamp: {e}")
            return None

    def _extract_playlist_id(self, parsed_url: ParseResult) -> Optional[str]:
        """Extract playlist ID from URL"""
        try:
            params = parse_qs(parsed_url.query)
            if 'list' in params:
                return params['list'][0]
            return None
        except (KeyError, IndexError) as e:
            logger.debug(f"Error extracting playlist ID: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error extracting playlist ID: {e}")
            return None

class URLExtractor:
    """Handles extraction of video URLs from messages"""

    def __init__(self) -> None:
        self.pattern_manager = URLPatternManager()
        self.validator = URLValidator(self.pattern_manager)
        self.metadata_extractor = URLMetadataExtractor(self.pattern_manager)
        self._url_cache: Dict[str, Set[str]] = {}

    async def extract_urls(
        self,
        message: discord.Message,
        enabled_sites: Optional[List[str]] = None
    ) -> List[URLMetadata]:
        """
        Extract video URLs from message content and attachments.
        
        Args:
            message: Discord message to extract URLs from
            enabled_sites: Optional list of enabled site identifiers
            
        Returns:
            List of URLMetadata objects for extracted URLs
        """
        urls: List[URLMetadata] = []
        
        try:
            # Check cache
            cache_key = f"{message.id}_{'-'.join(enabled_sites) if enabled_sites else 'all'}"
            if cache_key in self._url_cache:
                return [
                    metadata for url in self._url_cache[cache_key]
                    if (metadata := self.metadata_extractor.extract_metadata(url))
                ]

            # Extract URLs
            content_urls = await self._extract_from_content(message.content, enabled_sites)
            attachment_urls = await self._extract_from_attachments(message.attachments)
            
            # Process all URLs
            all_urls = content_urls + attachment_urls
            valid_urls: Set[str] = set()
            
            for url in all_urls:
                if not self.validator.is_valid_url(url):
                    logger.debug(f"Invalid URL format: {url}")
                    continue
                    
                metadata = self.metadata_extractor.extract_metadata(url)
                if not metadata:
                    logger.debug(f"Could not extract metadata from URL: {url}")
                    continue

                if not self.pattern_manager.is_supported_site(url, metadata.site, enabled_sites):
                    logger.debug(f"URL {url} doesn't match any enabled sites")
                    continue

                urls.append(metadata)
                valid_urls.add(url)

            # Update cache (ponytail: FIFO cap, one entry per message would grow forever)
            if len(self._url_cache) >= 1000:
                self._url_cache.pop(next(iter(self._url_cache)))
            self._url_cache[cache_key] = valid_urls
            
            return urls

        except Exception as e:
            logger.error(f"Error extracting URLs from message {message.id}: {e}", exc_info=True)
            return []

    async def _extract_from_content(
        self,
        content: Optional[str],
        enabled_sites: Optional[List[str]]
    ) -> List[str]:
        """Extract video URLs from message content"""
        if not content:
            return []

        try:
            urls = []
            for word in content.split():
                word = word.strip(URL_WRAPPING_CHARS)
                if self.validator.get_url_type(word) != URLType.UNKNOWN:
                    urls.append(word)
            return urls
        except Exception as e:
            logger.error(f"Error extracting URLs from content: {e}", exc_info=True)
            return []

    async def _extract_from_attachments(
        self,
        attachments: List[discord.Attachment]
    ) -> List[str]:
        """Extract video URLs from message attachments"""
        try:
            return [
                attachment.url
                for attachment in attachments
                if any(
                    attachment.filename.lower().endswith(ext)
                    for ext in self.pattern_manager.direct_extensions
                )
            ]
        except Exception as e:
            logger.error(f"Error extracting URLs from attachments: {e}", exc_info=True)
            return []

    def clear_cache(self, message_id: Optional[int] = None) -> None:
        """
        Clear URL cache.
        
        Args:
            message_id: Optional message ID to clear cache for. If None, clears all cache.
        """
        try:
            if message_id:
                keys_to_remove = [
                    key for key in self._url_cache
                    if key.startswith(f"{message_id}_")
                ]
                for key in keys_to_remove:
                    self._url_cache.pop(key, None)
            else:
                self._url_cache.clear()
        except Exception as e:
            logger.error(f"Error clearing URL cache: {e}", exc_info=True)
