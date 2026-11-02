"""Keeps yt-dlp on its latest release.

Sites change constantly and old yt-dlp builds stop working, so the cog
upgrades yt-dlp at startup and then once a day. A new version is swapped
in without a restart: the old yt_dlp modules are dropped from sys.modules,
re-imported, and rebound in every videoarchiver module that imported it.
"""

import asyncio
import importlib
import logging
import sys
from importlib.metadata import version as get_package_version
from typing import Optional, Tuple

logger = logging.getLogger("VideoArchiver")


class UpdateChecker:
    """Upgrades yt-dlp at startup and every UPDATE_INTERVAL seconds."""

    UPDATE_INTERVAL = 86400  # daily
    SUBPROCESS_TIMEOUT = 300

    def __init__(self) -> None:
        self._task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop())
            logger.info("yt-dlp daily updater started")

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None

    async def _loop(self) -> None:
        while True:
            try:
                ok, message = await self.update_yt_dlp()
                (logger.info if ok else logger.error)(message)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("yt-dlp update failed")
            await asyncio.sleep(self.UPDATE_INTERVAL)

    @staticmethod
    def _current_version() -> Optional[str]:
        try:
            return get_package_version("yt-dlp")
        except Exception:
            return None

    async def update_yt_dlp(self) -> Tuple[bool, str]:
        """pip-upgrade yt-dlp and hot-swap it in if the version changed."""
        before = self._current_version()
        process = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "pip", "install", "--upgrade", "--quiet", "yt-dlp",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, stderr = await asyncio.wait_for(
                process.communicate(), timeout=self.SUBPROCESS_TIMEOUT
            )
        except (asyncio.TimeoutError, asyncio.CancelledError) as e:
            # Don't leave pip writing to site-packages after unload
            process.kill()
            await process.wait()
            if isinstance(e, asyncio.CancelledError):
                raise
            return False, "yt-dlp update timed out"
        if process.returncode != 0:
            return False, f"yt-dlp update failed: {stderr.decode(errors='ignore').strip()}"

        after = self._current_version()
        if after == before:
            return True, f"yt-dlp is up to date ({after})"
        reload_yt_dlp()
        return True, f"Updated yt-dlp {before} -> {after}"


def reload_yt_dlp() -> None:
    """Load the freshly installed yt-dlp and point our modules at it.

    Downloads already running keep the old module objects and finish on them.
    """
    old = {m: sys.modules.pop(m) for m in list(sys.modules)
           if m == "yt_dlp" or m.startswith("yt_dlp.")}
    importlib.invalidate_caches()
    try:
        fresh = importlib.import_module("yt_dlp")
    except Exception:
        # Broken install: keep running on the version already loaded
        for m in [m for m in sys.modules if m == "yt_dlp" or m.startswith("yt_dlp.")]:
            del sys.modules[m]
        sys.modules.update(old)
        raise
    for name, module in list(sys.modules.items()):
        if name.startswith(__package__ + ".") and getattr(module, "yt_dlp", None) is not None:
            module.yt_dlp = fresh
