"""URL extraction functionality for video processing"""

import logging
import re
from enum import Enum
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Set, Pattern, ClassVar
from datetime import datetime
import discord
from urllib.parse import urlparse, parse_qs, ParseResult

logger = logging.getLogger("VideoArchiver")

@dataclass
class URLPattern:
    """Defines a URL pattern for a video site"""
    site: str
    pattern: Pattern
    requires_api: bool = False
    supports_timestamp: bool = False
    supports_playlist: bool = False

    def __post_init__(self) -> None:
        """Validate pattern after initialization"""
        if not isinstance(self.pattern, Pattern):
            raise ValueError("Pattern must be a compiled regular expression")

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

class URLPatternManager:
    """Manages URL patterns for different video sites"""

    YOUTUBE_PATTERN: ClassVar[Pattern] = re.compile(
        r'(?:https?://)?(?:www\.)?'
        r'(?:youtube\.com/watch\?v=|youtu\.be/)'
        r'([a-zA-Z0-9_-]{11})'
    )
    VIMEO_PATTERN: ClassVar[Pattern] = re.compile(
        r'(?:https?://)?(?:www\.)?'
        r'vimeo\.com/(?:channels/(?:\w+/)?|groups/(?:[^/]*/)*|)'
        r'(\d+)(?:|/\w+)*'
    )
    TWITTER_PATTERN: ClassVar[Pattern] = re.compile(
        r'(?:https?://)?(?:www\.)?'
        r'(?:twitter\.com|x\.com)/\w+/status/(\d+)'
    )

    def __init__(self) -> None:
        self.patterns: Dict[str, URLPattern] = {
            "youtube": URLPattern(
                site="youtube",
                pattern=self.YOUTUBE_PATTERN,
                supports_timestamp=True,
                supports_playlist=True
            ),
            "vimeo": URLPattern(
                site="vimeo",
                pattern=self.VIMEO_PATTERN,
                supports_timestamp=True
            ),
            "twitter": URLPattern(
                site="twitter",
                pattern=self.TWITTER_PATTERN,
                requires_api=True
            )
        }

        self.direct_extensions: Set[str] = {'.mp4', '.mov', '.avi', '.webm', '.mkv'}

    def get_pattern(self, site: str) -> Optional[URLPattern]:
        """
        Get pattern for a site.
        
        Args:
            site: Site identifier
            
        Returns:
            URLPattern for the site or None if not found
        """
        return self.patterns.get(site.lower())

    def is_supported_site(self, url: str, enabled_sites: Optional[List[str]]) -> bool:
        """
        Check if URL is from a supported site.
        
        Args:
            url: URL to check
            enabled_sites: List of enabled site identifiers
            
        Returns:
            True if site is supported, False otherwise
        """
        if not enabled_sites:
            return True

        try:
            parsed = urlparse(url.lower())
            domain = parsed.netloc.replace('www.', '')
            return any(site.lower() in domain for site in enabled_sites)
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
            if any(pattern.pattern.match(url) for pattern in self.pattern_manager.patterns.values()):
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
            for site, pattern in self.pattern_manager.patterns.items():
                if match := pattern.pattern.match(url):
                    metadata = URLMetadata(
                        url=url,
                        site=site,
                        video_id=match.group(1)
                    )
                    
                    # Extract additional metadata
                    if pattern.supports_timestamp:
                        metadata.timestamp = self._extract_timestamp(parsed)
                    if pattern.supports_playlist:
                        metadata.playlist_id = self._extract_playlist_id(parsed)
                    
                    return metadata

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
                    
                if not self.pattern_manager.is_supported_site(url, enabled_sites):
                    logger.debug(f"URL {url} doesn't match any enabled sites")
                    continue
                    
                metadata = self.metadata_extractor.extract_metadata(url)
                if metadata:
                    urls.append(metadata)
                    valid_urls.add(url)
                else:
                    logger.debug(f"Could not extract metadata from URL: {url}")

            # Update cache
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
