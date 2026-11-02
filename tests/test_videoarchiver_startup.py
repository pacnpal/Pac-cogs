"""Self-check for VideoArchiver startup and command registration. Needs Red-DiscordBot installed.

Run from the repo root: python tests/test_videoarchiver_startup.py
"""
import asyncio
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from redbot.core import _drivers, data_manager
from redbot.core._cli import parse_cli_flags
from redbot.core.bot import Red

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import videoarchiver  # noqa: E402
from videoarchiver.ffmpeg.ffmpeg_manager import FFmpegManager  # noqa: E402

GROUPS = ("archiver", "archivedb", "settings")


def app_command(bot, name):
    # Red keeps app commands "disabled" until `[p]slash enable`, but they're still on the tree
    return bot.tree._disabled_global_commands.get(name) or bot.tree.get_command(name)


async def load_and_check(bot):
    await videoarchiver.setup(bot)
    cog = bot.get_cog("VideoArchiver")
    assert cog is not None
    for name in GROUPS:
        assert bot.get_command(name) is not None, f"prefix command {name} missing"
        assert app_command(bot, name) is not None, f"app command {name} missing"
    assert bot.get_command("archiver enable") is not None
    assert bot.get_command("archivedb check") is not None
    assert bot.get_command("settings setchannel") is not None

    await asyncio.wait_for(cog.ready.wait(), timeout=30)
    assert cog.config_manager is not None and type(cog.config_manager).__name__ == "ConfigManager"
    assert type(cog.processor).__name__ == "VideoProcessor"
    assert type(cog.queue_manager).__name__ == "EnhancedVideoQueueManager"
    assert cog.ffmpeg_mgr is not None
    assert cog.data_path == data_manager.cog_data_path(cog) and cog.download_path.is_dir()
    assert cog.processor.config is cog.config_manager
    assert cog.processor.queue_manager is cog.queue_manager
    assert cog.processor.ffmpeg_mgr is cog.ffmpeg_mgr
    # Config actually round-trips through Red
    await cog.config_manager.update_setting(1, "enabled", True)
    assert await cog.config_manager.get_setting(1, "enabled") is True
    return cog


async def main():
    data_manager.basic_config = {"DATA_PATH": tempfile.mkdtemp(), "COG_PATH_APPEND": "cogs",
                                 "CORE_PATH_APPEND": "core", "STORAGE_TYPE": "JSON", "STORAGE_DETAILS": {}}
    data_manager.instance_name = "test"
    await _drivers.get_driver_class().initialize(**data_manager.storage_details())
    bot = Red(cli_flags=parse_cli_flags(["test"]), description="test")
    bot.is_owner = AsyncMock(return_value=False)

    # FFmpegManager may download binaries; startup only needs an object.
    with patch("videoarchiver.core.component_manager.FFmpegManager",
               lambda: MagicMock(spec=FFmpegManager)), \
         patch("videoarchiver.update_checker.UpdateChecker.update_yt_dlp",
               AsyncMock(return_value=(True, "stub"))):
        await load_and_check(bot)

        await videoarchiver.teardown(bot)
        assert bot.get_cog("VideoArchiver") is None
        for name in GROUPS:
            assert bot.get_command(name) is None, f"prefix command {name} left behind"
            assert app_command(bot, name) is None, f"app command {name} left behind"

        # Reload must not hit "already registered"
        cog = await load_and_check(bot)
        await bot.remove_cog("VideoArchiver")
        assert all(bot.get_command(n) is None for n in GROUPS)
        assert not cog.ready.is_set()

    print("videoarchiver startup ok")


if __name__ == "__main__":
    asyncio.run(main())
