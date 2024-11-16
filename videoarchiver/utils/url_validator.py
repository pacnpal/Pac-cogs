"""URL validation utilities for video downloads"""

import re
import logging
import yt_dlp
from typing import List, Optional

logger = logging.getLogger("VideoArchiver")

def is_video_url_pattern(url: str) -> bool:
    """Check if URL matches common video platform patterns"""
    video_patterns = [
        r"youtube\.com/watch\?v=",
        r"youtu\.be/",
        r"vimeo\.com/",
        r"tiktok\.com/",
        r"twitter\.com/.*/video/",
        r"x\.com/.*/video/",
        r"bsky\.app/",
        r"facebook\.com/.*/videos/",
        r"instagram\.com/.*/(tv|reel|p)/",
        r"twitch\.tv/.*/clip/",
        r"streamable\.com/",
        r"v\.redd\.it/",
        r"clips\.twitch\.tv/",
        r"dailymotion\.com/video/",
        r"\.mp4$",
        r"\.webm$",
        r"\.mov$",
    ]
    return any(re.search(pattern, url, re.IGNORECASE) for pattern in video_patterns)

def check_url_support(url: str, ydl_opts: dict, enabled_sites: Optional[List[str]] = None) -> bool:
    """Check if URL is supported by attempting a simulated download"""
    if not is_video_url_pattern(url):
        return False

    try:
        simulate_opts = {
            **ydl_opts,
            "simulate": True,
            "quiet": True,
            "no_warnings": True,
            "extract_flat": True,
            "skip_download": True,
            "format": "best",
        }

        with yt_dlp.YoutubeDL(simulate_opts) as ydl:
            try:
                info = ydl.extract_info(url, download=False)
                if info is None:
                    return False

                if enabled_sites:
                    extractor = info.get("extractor", "").lower()
                    if not any(
                        site.lower() in extractor for site in enabled_sites
                    ):
                        logger.info(f"Site {extractor} not in enabled sites list")
                        return False

                logger.info(
                    f"URL supported: {url} (Extractor: {info.get('extractor', 'unknown')})"
                )
                return True

            except yt_dlp.utils.UnsupportedError:
                return False
            except Exception as e:
                if "Unsupported URL" not in str(e):
                    logger.error(f"Error checking URL {url}: {str(e)}")
                return False

    except Exception as e:
        logger.error