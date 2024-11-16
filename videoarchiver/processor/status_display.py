"""Module for handling queue status display and formatting"""

import discord
from enum import Enum
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Any, List, Optional
import logging

logger = logging.getLogger("VideoArchiver")

class DisplayTheme:
    """Defines display themes"""
    DEFAULT = {
        "title_color": discord.Color.blue(),
        "success_color": discord.Color.green(),
        "warning_color": discord.Color.gold(),
        "error_color": discord.Color.red(),
        "info_color": discord.Color.blurple()
    }

@dataclass
class DisplayTemplate:
    """Template for status display sections"""
    name: str
    format_string: str
    inline: bool = False
    order: int = 0
    condition: Optional[str] = None

class DisplaySection(Enum):
    """Available display sections"""
    QUEUE_STATS = "queue_stats"
    DOWNLOADS = "downloads"
    COMPRESSIONS = "compressions"
    ERRORS = "errors"
    HARDWARE = "hardware"

class StatusFormatter:
    """Formats status information for display"""

    @staticmethod
    def format_bytes(bytes: int) -> str:
        """Format bytes into human readable format"""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if bytes < 1024:
                return f"{bytes:.1f}{unit}"
            bytes /= 1024
        return f"{bytes:.1f}TB"

    @staticmethod
    def format_time(seconds: float) -> str:
        """Format time duration"""
        if seconds < 60:
            return f"{seconds:.1f}s"
        minutes = seconds / 60
        if minutes < 60:
            return f"{minutes:.1f}m"
        hours = minutes / 60
        return f"{hours:.1f}h"

    @staticmethod
    def format_percentage(value: float) -> str:
        """Format percentage value"""
        return f"{value:.1f}%"

class DisplayManager:
    """Manages status display configuration"""

    def __init__(self):
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
                order=2
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
                order=3
            ),
            DisplaySection.ERRORS: DisplayTemplate(
                name="Error Statistics",
                format_string="```\n{error_stats}```",
                condition="has_errors",
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
        self.theme = DisplayTheme.DEFAULT

class StatusDisplay:
    """Handles formatting and display of queue status information"""

    def __init__(self):
        self.display_manager = DisplayManager()
        self.formatter = StatusFormatter()

    async def create_queue_status_embed(
        self,
        queue_status: Dict[str, Any],
        active_ops: Dict[str, Any]
    ) -> discord.Embed:
        """Create an embed displaying queue status and active operations"""
        embed = discord.Embed(
            title="Queue Status Details",
            color=self.display_manager.theme["title_color"],
            timestamp=datetime.utcnow()
        )

        # Add sections in order
        sections = sorted(
            self.display_manager.templates.items(),
            key=lambda x: x[1].order
        )

        for section, template in sections:
            # Check condition if exists
            if template.condition:
                if not self._check_condition(template.condition, queue_status, active_ops):
                    continue

            # Add section based on type
            if section == DisplaySection.QUEUE_STATS:
                self._add_queue_statistics(embed, queue_status, template)
            elif section == DisplaySection.DOWNLOADS:
                self._add_active_downloads(embed, active_ops.get('downloads', {}), template)
            elif section == DisplaySection.COMPRESSIONS:
                self._add_active_compressions(embed, active_ops.get('compressions', {}), template)
            elif section == DisplaySection.ERRORS:
                self._add_error_statistics(embed, queue_status, template)
            elif section == DisplaySection.HARDWARE:
                self._add_hardware_statistics(embed, queue_status, template)

        return embed

    def _check_condition(
        self,
        condition: str,
        queue_status: Dict[str, Any],
        active_ops: Dict[str, Any]
    ) -> bool:
        """Check if condition for displaying section is met"""
        if condition == "has_errors":
            return bool(queue_status["metrics"]["errors_by_type"])
        return True

    def _add_queue_statistics(
        self,
        embed: discord.Embed,
        queue_status: Dict[str, Any],
        template: DisplayTemplate
    ) -> None:
        """Add queue statistics to the embed"""
        embed.add_field(
            name=template.name,
            value=template.format_string.format(
                pending=queue_status['pending'],
                processing=queue_status['processing'],
                completed=queue_status['completed'],
                failed=queue_status['failed'],
                success_rate=self.formatter.format_percentage(
                    queue_status['metrics']['success_rate'] * 100
                ),
                avg_processing_time=self.formatter.format_time(
                    queue_status['metrics']['avg_processing_time']
                )
            ),
            inline=template.inline
        )

    def _add_active_downloads(
        self,
        embed: discord.Embed,
        downloads: Dict[str, Any],
        template: DisplayTemplate
    ) -> None:
        """Add active downloads information to the embed"""
        if downloads:
            content = []
            for url, progress in downloads.items():
                content.append(template.format_string.format(
                    url=url[:50] + "..." if len(url) > 50 else url,
                    percent=self.formatter.format_percentage(progress.get('percent', 0)),
                    speed=progress.get('speed', 'N/A'),
                    eta=progress.get('eta', 'N/A'),
                    size=f"{self.formatter.format_bytes(progress.get('downloaded_bytes', 0))}/"
                         f"{self.formatter.format_bytes(progress.get('total_bytes', 0))}",
                    start_time=progress.get('start_time', 'N/A'),
                    retries=progress.get('retries', 0)
                ))
            embed.add_field(
                name=template.name,
                value="".join(content),
                inline=template.inline
            )
        else:
            embed.add_field(
                name=template.name,
                value="```\nNo active downloads```",
                inline=template.inline
            )

    def _add_active_compressions(
        self,
        embed: discord.Embed,
        compressions: Dict[str, Any],
        template: DisplayTemplate
    ) -> None:
        """Add active compressions information to the embed"""
        if compressions:
            content = []
            for file_id, progress in compressions.items():
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
            embed.add_field(
                name=template.name,
                value="".join(content),
                inline=template.inline
            )
        else:
            embed.add_field(
                name=template.name,
                value="```\nNo active compressions```",
                inline=template.inline
            )

    def _add_error_statistics(
        self,
        embed: discord.Embed,
        queue_status: Dict[str, Any],
        template: DisplayTemplate
    ) -> None:
        """Add error statistics to the embed"""
        if queue_status["metrics"]["errors_by_type"]:
            error_stats = "\n".join(
                f"{error_type}: {count}"
                for error_type, count in queue_status["metrics"]["errors_by_type"].items()
            )
            embed.add_field(
                name=template.name,
                value=template.format_string.format(error_stats=error_stats),
                inline=template.inline
            )

    def _add_hardware_statistics(
        self,
        embed: discord.Embed,
        queue_status: Dict[str, Any],
        template: DisplayTemplate
    ) -> None:
        """Add hardware statistics to the embed"""
        embed.add_field(
            name=template.name,
            value=template.format_string.format(
                hw_failures=queue_status['metrics']['hardware_accel_failures'],
                comp_failures=queue_status['metrics']['compression_failures'],
                memory_usage=self.formatter.format_bytes(
                    queue_status['metrics']['peak_memory_usage'] * 1024 * 1024  # Convert MB to bytes
                )
            ),
            inline=template.inline
        )
