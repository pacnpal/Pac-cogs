"""Module for handling queue status display and formatting"""

import logging
from enum import Enum, auto
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Any, List, Optional, Callable, TypeVar, Union, TypedDict, ClassVar, Tuple
import discord

from videoarchiver.utils.exceptions import DisplayError

logger = logging.getLogger("VideoArchiver")

T = TypeVar('T')

class DisplayTheme(TypedDict):
    """Type definition for display theme"""
    title_color: discord.Color
    success_color: discord.Color
    warning_color: discord.Color
    error_color: discord.Color
    info_color: discord.Color

class DisplaySection(Enum):
    """Available display sections"""
    QUEUE_STATS = auto()
    DOWNLOADS = auto()
    COMPRESSIONS = auto()
    ERRORS = auto()
    HARDWARE = auto()

class DisplayCondition(Enum):
    """Display conditions for sections"""
    HAS_ERRORS = "has_errors"
    HAS_DOWNLOADS = "has_downloads"
    HAS_COMPRESSIONS = "has_compressions"

@dataclass
class DisplayTemplate:
    """Template for status display sections"""
    name: str
    format_string: str
    inline: bool = False
    order: int = 0
    condition: Optional[DisplayCondition] = None
    formatter: Optional[Callable[[Dict[str, Any]], str]] = None
    max_items: int = field(default=5)  # Maximum items to display in lists

class StatusFormatter:
    """Formats status information for display"""

    BYTE_UNITS: ClassVar[List[str]] = ['B', 'KB', 'MB', 'GB', 'TB']
    TIME_THRESHOLDS: ClassVar[List[Tuple[float, str]]] = [
        (60, 's'),
        (3600, 'm'),
        (float('inf'), 'h')
    ]

    @staticmethod
    def format_bytes(bytes_value: Union[int, float]) -> str:
        """
        Format bytes into human readable format.
        
        Args:
            bytes_value: Number of bytes to format
            
        Returns:
            Formatted string with appropriate unit
            
        Raises:
            ValueError: If bytes_value is negative
        """
        if bytes_value < 0:
            raise ValueError("Bytes value cannot be negative")

        bytes_num = float(bytes_value)
        for unit in StatusFormatter.BYTE_UNITS:
            if bytes_num < 1024:
                return f"{bytes_num:.1f}{unit}"
            bytes_num /= 1024
        return f"{bytes_num:.1f}TB"

    @staticmethod
    def format_time(seconds: float) -> str:
        """
        Format time duration.
        
        Args:
            seconds: Number of seconds to format
            
        Returns:
            Formatted time string
            
        Raises:
            ValueError: If seconds is negative
        """
        if seconds < 0:
            raise ValueError("Time value cannot be negative")

        for threshold, unit in StatusFormatter.TIME_THRESHOLDS:
            if seconds < threshold:
                return f"{seconds:.1f}{unit}"
            seconds /= 60
        return f"{seconds:.1f}h"

    @staticmethod
    def format_percentage(value: float) -> str:
        """
        Format percentage value.
        
        Args:
            value: Percentage value to format (0-100)
            
        Returns:
            Formatted percentage string
            
        Raises:
            ValueError: If value is outside valid range
        """
        if not 0 <= value <= 100:
            raise ValueError("Percentage must be between 0 and 100")
        return f"{value:.1f}%"

    @staticmethod
    def truncate_url(url: str, max_length: int = 50) -> str:
        """
        Truncate URL to specified length.
        
        Args:
            url: URL to truncate
            max_length: Maximum length for URL
            
        Returns:
            Truncated URL string
            
        Raises:
            ValueError: If max_length is less than 4
        """
        if max_length < 4:  # Need room for "..."
            raise ValueError("max_length must be at least 4")
        return f"{url[:max_length]}..." if len(url) > max_length else url

class DisplayManager:
    """Manages status display configuration"""

    DEFAULT_THEME: ClassVar[DisplayTheme] = DisplayTheme(
        title_color=discord.Color.blue(),
        success_color=discord.Color.green(),
        warning_color=discord.Color.gold(),
        error_color=discord.Color.red(),
        info_color=discord.Color.blurple()
    )

    def __init__(self) -> None:
        self.templates: Dict[DisplaySection, DisplayTemplate] = {
            DisplaySection.QUEUE_STATS: DisplayTemplate(
                name="Queue Statistics",
                format_string=(
                    "```\n"
                    "Pending: {pending}\n"
                    "Processing: {processing}\n"
                    "Completed: {completed}\n"
                    "Failed: {failed}\n"
                    "Success Rate: {success_rate}\n"
                    "Avg Processing Time: {avg_processing_time}\n"
                    "```"
                ),
                order=1
            ),
            DisplaySection.DOWNLOADS: DisplayTemplate(
                name="Active Downloads",
                format_string=(
                    "```\n"
                    "URL: {url}\n"
                    "Progress: {percent}\n"
                    "Speed: {speed}\n"
                    "ETA: {eta}\n"
                    "Size: {size}\n"
                    "Started: {start_time}\n"
                    "Retries: {retries}\n"
                    "```"
                ),
                order=2,
                condition=DisplayCondition.HAS_DOWNLOADS
            ),
            DisplaySection.COMPRESSIONS: DisplayTemplate(
                name="Active Compressions",
                format_string=(
                    "```\n"
                    "File: {filename}\n"
                    "Progress: {percent}\n"
                    "Time Elapsed: {elapsed_time}\n"
                    "Input Size: {input_size}\n"
                    "Current Size: {current_size}\n"
                    "Target Size: {target_size}\n"
                    "Codec: {codec}\n"
                    "Hardware Accel: {hardware_accel}\n"
                    "```"
                ),
                order=3,
                condition=DisplayCondition.HAS_COMPRESSIONS
            ),
            DisplaySection.ERRORS: DisplayTemplate(
                name="Error Statistics",
                format_string="```\n{error_stats}```",
                condition=DisplayCondition.HAS_ERRORS,
                order=4
            ),
            DisplaySection.HARDWARE: DisplayTemplate(
                name="Hardware Statistics",
                format_string=(
                    "```\n"
                    "Hardware Accel Failures: {hw_failures}\n"
                    "Compression Failures: {comp_failures}\n"
                    "Peak Memory Usage: {memory_usage}\n"
                    "```"
                ),
                order=5
            )
        }
        self.theme = self.DEFAULT_THEME.copy()

class StatusDisplay:
    """Handles formatting and display of queue status information"""

    def __init__(self) -> None:
        self.display_manager = DisplayManager()
        self.formatter = StatusFormatter()

    @classmethod
    async def create_queue_status_embed(
        cls,
        queue_status: Dict[str, Any],
        active_ops: Dict[str, Any]
    ) -> discord.Embed:
        """
        Create an embed displaying queue status and active operations.
        
        Args:
            queue_status: Dictionary containing queue status information
            active_ops: Dictionary containing active operations information
            
        Returns:
            Discord embed containing formatted status information
            
        Raises:
            DisplayError: If there's an error creating the embed
        """
        try:
            display = cls()
            embed = discord.Embed(
                title="Queue Status Details",
                color=display.display_manager.theme["title_color"],
                timestamp=datetime.utcnow()
            )

            # Add sections in order
            sections = sorted(
                display.display_manager.templates.items(),
                key=lambda x: x[1].order
            )

            for section, template in sections:
                try:
                    # Check condition if exists
                    if template.condition:
                        if not display._check_condition(
                            template.condition,
                            queue_status,
                            active_ops
                        ):
                            continue

                    # Add section based on type
                    if section == DisplaySection.QUEUE_STATS:
                        display._add_queue_statistics(embed, queue_status, template)
                    elif section == DisplaySection.DOWNLOADS:
                        display._add_active_downloads(embed, active_ops.get('downloads', {}), template)
                    elif section == DisplaySection.COMPRESSIONS:
                        display._add_active_compressions(embed, active_ops.get('compressions', {}), template)
                    elif section == DisplaySection.ERRORS:
                        display._add_error_statistics(embed, queue_status, template)
                    elif section == DisplaySection.HARDWARE:
                        display._add_hardware_statistics(embed, queue_status, template)
                except Exception as e:
                    logger.error(f"Error adding section {section.value}: {e}")
                    # Continue with other sections

            return embed

        except Exception as e:
            error = f"Error creating status embed: {str(e)}"
            logger.error(error, exc_info=True)
            raise DisplayError(error)

    def _check_condition(
        self,
        condition: DisplayCondition,
        queue_status: Dict[str, Any],
        active_ops: Dict[str, Any]
    ) -> bool:
        """Check if condition for displaying section is met"""
        try:
            if condition == DisplayCondition.HAS_ERRORS:
                return bool(queue_status.get("metrics", {}).get("errors_by_type"))
            elif condition == DisplayCondition.HAS_DOWNLOADS:
                return bool(active_ops.get("downloads"))
            elif condition == DisplayCondition.HAS_COMPRESSIONS:
                return bool(active_ops.get("compressions"))
            return True
        except Exception as e:
            logger.error(f"Error checking condition {condition}: {e}")
            return False

    def _add_queue_statistics(
        self,
        embed: discord.Embed,
        queue_status: Dict[str, Any],
        template: DisplayTemplate
    ) -> None:
        """Add queue statistics to the embed"""
        try:
            metrics = queue_status.get('metrics', {})
            embed.add_field(
                name=template.name,
                value=template.format_string.format(
                    pending=queue_status.get('pending', 0),
                    processing=queue_status.get('processing', 0),
                    completed=queue_status.get('completed', 0),
                    failed=queue_status.get('failed', 0),
                    success_rate=self.formatter.format_percentage(
                        metrics.get('success_rate', 0) * 100
                    ),
                    avg_processing_time=self.formatter.format_time(
                        metrics.get('avg_processing_time', 0)
                    )
                ),
                inline=template.inline
            )
        except Exception as e:
            logger.error(f"Error adding queue statistics: {e}")
            embed.add_field(
                name=template.name,
                value="```\nError displaying queue statistics```",
                inline=template.inline
            )

    def _add_active_downloads(
        self,
        embed: discord.Embed,
        downloads: Dict[str, Any],
        template: DisplayTemplate
    ) -> None:
        """Add active downloads information to the embed"""
        try:
            if downloads:
                content = []
                for url, progress in list(downloads.items())[:template.max_items]:
                    try:
                        content.append(template.format_string.format(
                            url=self.formatter.truncate_url(url),
                            percent=self.formatter.format_percentage(progress.get('percent', 0)),
                            speed=progress.get('speed', 'N/A'),
                            eta=progress.get('eta', 'N/A'),
                            size=f"{self.formatter.format_bytes(progress.get('downloaded_bytes', 0))}/"
                                 f"{self.formatter.format_bytes(progress.get('total_bytes', 0))}",
                            start_time=progress.get('start_time', 'N/A'),
                            retries=progress.get('retries', 0)
                        ))
                    except Exception as e:
                        logger.error(f"Error formatting download {url}: {e}")
                        continue

                if len(downloads) > template.max_items:
                    content.append(f"\n... and {len(downloads) - template.max_items} more")

                embed.add_field(
                    name=template.name,
                    value="".join(content) if content else "```\nNo active downloads```",
                    inline=template.inline
                )
            else:
                embed.add_field(
                    name=template.name,
                    value="```\nNo active downloads```",
                    inline=template.inline
                )
        except Exception as e:
            logger.error(f"Error adding active downloads: {e}")
            embed.add_field(
                name=template.name,
                value="```\nError displaying downloads```",
                inline=template.inline
            )

    def _add_active_compressions(
        self,
        embed: discord.Embed,
        compressions: Dict[str, Any],
        template: DisplayTemplate
    ) -> None:
        """Add active compressions information to the embed"""
        try:
            if compressions:
                content = []
                for file_id, progress in list(compressions.items())[:template.max_items]:
                    try:
                        content.append(template.format_string.format(
                            filename=progress.get('filename', 'Unknown'),
                            percent=self.formatter.format_percentage(progress.get('percent', 0)),
                            elapsed_time=progress.get('elapsed_time', 'N/A'),
                            input_size=self.formatter.format_bytes(progress.get('input_size', 0)),
                            current_size=self.formatter.format_bytes(progress.get('current_size', 0)),
                            target_size=self.formatter.format_bytes(progress.get('target_size', 0)),
                            codec=progress.get('codec', 'Unknown'),
                            hardware_accel=progress.get('hardware_accel', False)
                        ))
                    except Exception as e:
                        logger.error(f"Error formatting compression {file_id}: {e}")
                        continue

                if len(compressions) > template.max_items:
                    content.append(f"\n... and {len(compressions) - template.max_items} more")

                embed.add_field(
                    name=template.name,
                    value="".join(content) if content else "```\nNo active compressions```",
                    inline=template.inline
                )
            else:
                embed.add_field(
                    name=template.name,
                    value="```\nNo active compressions```",
                    inline=template.inline
                )
        except Exception as e:
            logger.error(f"Error adding active compressions: {e}")
            embed.add_field(
                name=template.name,
                value="```\nError displaying compressions```",
                inline=template.inline
            )

    def _add_error_statistics(
        self,
        embed: discord.Embed,
        queue_status: Dict[str, Any],
        template: DisplayTemplate
    ) -> None:
        """Add error statistics to the embed"""
        try:
            metrics = queue_status.get('metrics', {})
            errors_by_type = metrics.get('errors_by_type', {})
            if errors_by_type:
                error_stats = "\n".join(
                    f"{error_type}: {count}"
                    for error_type, count in list(errors_by_type.items())[:template.max_items]
                )
                if len(errors_by_type) > template.max_items:
                    error_stats += f"\n... and {len(errors_by_type) - template.max_items} more"
                embed.add_field(
                    name=template.name,
                    value=template.format_string.format(error_stats=error_stats),
                    inline=template.inline
                )
        except Exception as e:
            logger.error(f"Error adding error statistics: {e}")
            embed.add_field(
                name=template.name,
                value="```\nError displaying error statistics```",
                inline=template.inline
            )

    def _add_hardware_statistics(
        self,
        embed: discord.Embed,
        queue_status: Dict[str, Any],
        template: DisplayTemplate
    ) -> None:
        """Add hardware statistics to the embed"""
        try:
            metrics = queue_status.get('metrics', {})
            embed.add_field(
                name=template.name,
                value=template.format_string.format(
                    hw_failures=metrics.get('hardware_accel_failures', 0),
                    comp_failures=metrics.get('compression_failures', 0),
                    memory_usage=self.formatter.format_bytes(
                        metrics.get('peak_memory_usage', 0) * 1024 * 1024  # Convert MB to bytes
                    )
                ),
                inline=template.inline
            )
        except Exception as e:
            logger.error(f"Error adding hardware statistics: {e}")
            embed.add_field(
                name=template.name,
                value="```\nError displaying hardware statistics```",
                inline=template.inline
            )
