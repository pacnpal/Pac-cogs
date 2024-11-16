"""URL extraction functionality for video processing"""

import logging
import re
from enum import Enum
from dataclasses import dataclass
from typing import List, Dict, Optional, Set, Pattern
import discord
from urllib.parse import urlparse, parse_qs

logger = logging.getLogger("VideoArchiver")

@dataclass
class URLPattern:
    """Defines a URL pattern for a video site"""
    site: str
    pattern: Pattern
    requires_api: bool = False
    supports_timestamp: bool = False
    supports_playlist: bool = False

@dataclass
class URLMetadata:
    """Metadata about an extracted URL"""
    url: str
    site: str
    timestamp: Optional[int] = None
    playlist_id: Optional[str] = None
    video_id: Optional[str] = None
    quality: Optional[str] = None

class URLType(Enum):
    """Types of video URLs"""
    DIRECT = "direct"
    PLATFORM = "platform"
    UNKNOWN = "unknown"

class URLPatternManager:
    """Manages URL patterns for different video sites"""

    def __init__(self):
        self.patterns: Dict[str, URLPattern] = {
            "youtube": URLPattern(
                site="youtube",
                pattern=re.compile(
                    r'(?:https?://)?(?:www\.)?'
                    r'(?:youtube\.com/watch\?v=|youtu\.be/)'
                    r'([a-zA-Z0-9_-]{11})'
                ),
                supports_timestamp=True,
                supports_playlist=True
            ),
            "vimeo": URLPattern(
                site="vimeo",
                pattern=re.compile(
                    r'(?:https?://)?(?:www\.)?'
                    r'vimeo\.com/(?:channels/(?:\w+/)?|groups/(?:[^/]*/)*|)'
                    r'(\d+)(?:|/\w+)*'
                ),
                supports_timestamp=True
            ),
            "twitter": URLPattern(
                site="twitter",
                pattern=re.compile(
                    r'(?:https?://)?(?:www\.)?'
                    r'(?:twitter\.com|x\.com)/\w+/status/(\d+)'
                ),
                requires_api=True
            ),
            # Add more patterns as needed
        }

        self.direct_extensions = {'.mp4', '.mov', '.avi', '.webm', '.mkv'}

    def get_pattern(self, site: str) -> Optional[URLPattern]:
        """Get pattern for a site"""
        return self.patterns.get(site.lower())

    def is_supported_site(self, url: str, enabled_sites: Optional[List[str]]) -> bool:
        """Check if URL is from a supported site"""
        if not enabled_sites:
            return True

        parsed = urlparse(url.lower())
        domain = parsed.netloc.replace('www.', '')
        return any(site.lower() in domain for site in enabled_sites)

class URLValidator:
    """Validates extracted URLs"""

    def __init__(self, pattern_manager: URLPatternManager):
        self.pattern_manager = pattern_manager

    def get_url_type(self, url: str) -> URLType:
        """Determine URL type"""
        parsed = urlparse(url)
        if any(parsed.path.lower().endswith(ext) for ext in self.pattern_manager.direct_extensions):
            return URLType.DIRECT
        if any(pattern.pattern.match(url) for pattern in self.pattern_manager.patterns.values()):
            return URLType.PLATFORM
        return URLType.UNKNOWN

    def is_valid_url(self, url: str) -> bool:
        """Validate URL format"""
        try:
            result = urlparse(url)
            return all([result.scheme, result.netloc])
        except Exception:
            return False

class URLMetadataExtractor:
    """Extracts metadata from URLs"""

    def __init__(self, pattern_manager: URLPatternManager):
        self.pattern_manager = pattern_manager

    def extract_metadata(self, url: str) -> Optional[URLMetadata]:
        """Extract metadata from URL"""
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
            logger.error(f"Error extracting metadata from URL {url}: {e}")
            return None

    def _extract_timestamp(self, parsed_url: urlparse) -> Optional[int]:
        """Extract timestamp from URL"""
        try:
            params = parse_qs(parsed_url.query)
            if 't' in params:
                return int(params['t'][0])
            return None
        except Exception:
            return None

    def _extract_playlist_id(self, parsed_url: urlparse) -> Optional[str]:
        """Extract playlist ID from URL"""
        try:
            params = parse_qs(parsed_url.query)
            if 'list' in params:
                return params['list'][0]
            return None
        except Exception:
            return None

class URLExtractor:
    """Handles extraction of video URLs from messages"""

    def __init__(self):
        self.pattern_manager = URLPatternManager()
        self.validator = URLValidator(self.pattern_manager)
        self.metadata_extractor = URLMetadataExtractor(self.pattern_manager)
        self._url_cache: Dict[str, Set[str]] = {}

    async def extract_urls(
        self,
        message: discord.Message,
        enabled_sites: Optional[List[str]] = None
    ) -> List[URLMetadata]:
        """Extract video URLs from message content and attachments"""
        urls = []
        
        # Check cache
        cache_key = f"{message.id}_{'-'.join(enabled_sites) if enabled_sites else 'all'}"
        if cache_key in self._url_cache:
            return [
                self.metadata_extractor.extract_metadata(url)
                for url in self._url_cache[cache_key]
                if url  # Filter out None values
            ]

        # Extract URLs
        content_urls = await self._extract_from_content(message.content, enabled_sites)
        attachment_urls = await self._extract_from_attachments(message.attachments)
        
        # Process all URLs
        all_urls = content_urls + attachment_urls
        valid_urls = []
        
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
                valid_urls.append(url)
            else:
                logger.debug(f"Could not extract metadata from URL: {url}")

        # Update cache
        self._url_cache[cache_key] = set(valid_urls)
        
        return urls

    async def _extract_from_content(
        self,
        content: str,
        enabled_sites: Optional[List[str]]
    ) -> List[str]:
        """Extract video URLs from message content"""
        if not content:
            return []

        urls = []
        for word in content.split():
            if self.validator.get_url_type(word) != URLType.UNKNOWN:
                urls.append(word)

        return urls

    async def _extract_from_attachments(
        self,
        attachments: List[discord.Attachment]
    ) -> List[str]:
        """Extract video URLs from message attachments"""
        return [
            attachment.url
            for attachment in attachments
            if any(
                attachment.filename.lower().endswith(ext)
                for ext in self.pattern_manager.direct_extensions
            )
        ]

    def clear_cache(self, message_id: Optional[int] = None) -> None:
        """Clear URL cache"""
        if message_id:
            keys_to_remove = [
                key for key in self._url_cache
                if key.startswith(f"{message_id}_")
            ]
            for key in keys_to_remove:
                self._url_cache.pop(key, None)
        else:
            self._url_cache.clear()
