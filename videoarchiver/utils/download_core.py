"""Old name for the downloader; core/guild.py still imports DownloadCore from here."""

from .download_manager import DownloadManager as DownloadCore

__all__ = ["DownloadCore"]
