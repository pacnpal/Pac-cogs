"""Self-check: a message with a video URL ends up uploaded to the archive channel. Needs Red-DiscordBot.

Loads the cog, configures a guild (archive + monitored channel), marks the bot ready, then
feeds a fake message through the registered on_message listener. The guild downloader's
download_video is mocked to return a small temp file and the archive channel's send is mocked.
Checks the item is queued, processed by the running queue processor and uploaded with a file;
that get_queue_status returns real counts; and that an idle processor reads as healthy.
Fails on any ERROR record.

Run from the repo root: python tests/test_videoarchiver_pipeline.py
"""
import asyncio
import logging
import os
import sys
import tempfile
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import discord
from redbot.core import _drivers, data_manager
from redbot.core._cli import parse_cli_flags
from redbot.core.bot import Red

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import videoarchiver  # noqa: E402
from videoarchiver.core.c_types import QueueState  # noqa: E402
from videoarchiver.ffmpeg.ffmpeg_manager import FFmpegManager  # noqa: E402
from videoarchiver.queue.processor import ProcessingStrategy as ProcessorStrategy  # noqa: E402
from videoarchiver.queue.q_types import ProcessingStrategy  # noqa: E402

GUILD, ARCHIVE, MONITORED, OTHER = 1001, 2001, 2002, 2003
URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


class ErrorCollector(logging.Handler):
    def __init__(self):
        super().__init__(logging.ERROR)
        self.records = []

    def emit(self, record):
        self.records.append(record)


def text_channel(cid, name):
    channel = MagicMock(spec=discord.TextChannel)
    channel.id, channel.name = cid, name
    channel.send = AsyncMock(return_value=MagicMock(attachments=[]))
    return channel


def fake_message(mid, guild, channel, content):
    msg = MagicMock(spec=discord.Message)
    msg.id, msg.guild, msg.channel, msg.content = mid, guild, channel, content
    msg.author = MagicMock(bot=False, id=42, roles=[], mention="<@42>", display_name="poster")
    msg.attachments = []
    msg.created_at = datetime.now(timezone.utc)
    msg.jump_url = f"https://discord.com/channels/{GUILD}/{channel.id}/{mid}"
    msg.add_reaction = AsyncMock()
    msg.remove_reaction = AsyncMock()
    channel.fetch_message = AsyncMock(return_value=msg)
    return msg


async def wait_for(cond, what, timeout=10):
    for _ in range(int(timeout / 0.02)):
        if cond():
            return
        await asyncio.sleep(0.02)
    raise AssertionError(f"timed out waiting for {what}")


async def main():
    assert ProcessorStrategy is ProcessingStrategy  # one definition, so CONCURRENT matches

    data_manager.basic_config = {"DATA_PATH": tempfile.mkdtemp(), "COG_PATH_APPEND": "cogs",
                                 "CORE_PATH_APPEND": "core", "STORAGE_TYPE": "JSON", "STORAGE_DETAILS": {}}
    data_manager.instance_name = "test"
    await _drivers.get_driver_class().initialize(**data_manager.storage_details())
    bot = Red(cli_flags=parse_cli_flags(["test"]), description="test")
    bot.is_owner = AsyncMock(return_value=False)
    bot.get_context = AsyncMock(return_value=MagicMock(valid=False))  # not a command

    archive, monitored, other = (text_channel(ARCHIVE, "archive"), text_channel(MONITORED, "clips"),
                                 text_channel(OTHER, "chat"))
    channels = {c.id: c for c in (archive, monitored, other)}
    guild = MagicMock(spec=discord.Guild)
    guild.id = GUILD
    guild.get_channel = channels.get
    bot.get_guild = {GUILD: guild}.get
    bot.get_channel = channels.get

    errors = ErrorCollector()
    logging.getLogger().addHandler(errors)
    with ExitStack() as stack:
        stack.enter_context(patch("videoarchiver.core.component_manager.FFmpegManager",
                                  lambda: MagicMock(spec=FFmpegManager)))
        stack.enter_context(patch("videoarchiver.update_checker.UpdateChecker.update_yt_dlp",
                                  AsyncMock(return_value=(True, "stub"))))
        stack.enter_context(patch.object(Red, "guilds", new_callable=PropertyMock, return_value=[guild]))

        await videoarchiver.setup(bot)
        cog = bot.get_cog("VideoArchiver")
        await asyncio.wait_for(cog.ready.wait(), timeout=30)
        qm, processor = cog.queue_manager, cog.processor

        # #6: idle processor (no finished operations) counts as healthy
        await wait_for(lambda: "operations" in processor.health_monitor.health_status, "health check")
        assert processor.health_monitor.health_status["operations"] is True

        guild_conf = cog.config.guild_from_id(GUILD)
        await guild_conf.enabled.set(True)
        await guild_conf.archive_channel.set(ARCHIVE)
        await guild_conf.monitored_channels.set([MONITORED])

        # Processing waits for the gateway; then it builds each guild's downloader
        assert not qm._processing_task.done()
        assert GUILD not in cog.components
        bot._red_ready.set()
        await wait_for(lambda: GUILD in cog.components, "guild components")

        fd, video = tempfile.mkstemp(suffix=".mp4")
        os.write(fd, b"\0" * 1024)
        os.close(fd)
        download = AsyncMock(return_value=(True, video, None))
        cog.components[GUILD]["downloader"].download_video = download
        add_to_queue = AsyncMock(wraps=qm.add_to_queue)
        processor.message_handler.queue_manager.add_to_queue = add_to_queue

        # A real archive DB, wired in the way `archivedb enable` does it
        from videoarchiver.database.video_archive_db import VideoArchiveDB
        db_dir = Path(tempfile.mkdtemp())
        VideoArchiveDB(db_dir)  # opened before, as after a restart: reopening used to fail
        db = VideoArchiveDB(db_dir)
        processor.db = processor.queue_handler.db = db
        archive.send.return_value = MagicMock(id=9999, delete=AsyncMock(),
                                              attachments=[MagicMock(url="https://cdn.example/v.mp4", size=123)])
        mm = cog.components[GUILD]["message_manager"]
        schedule = mm.schedule_message_deletion = AsyncMock(wraps=mm.schedule_message_deletion)

        on_message = bot.extra_events["on_message"]
        assert len(on_message) == 1, on_message

        # Unmonitored channel: ignored before queueing
        await on_message[0](fake_message(3000, guild, other, f"see {URL}"))
        await asyncio.sleep(0.2)
        assert not add_to_queue.called

        await on_message[0](fake_message(3001, guild, monitored, f"look {URL}"))
        await wait_for(lambda: archive.send.called, "upload to archive channel")
        add_to_queue.assert_awaited_once()
        assert add_to_queue.call_args.kwargs["url"] == URL
        assert download.call_args.args[0] == URL
        sent = archive.send.call_args.kwargs
        assert isinstance(sent["file"], discord.File), sent
        assert "poster" in sent["content"] and "clips" in sent["content"], sent["content"]
        # message_duration (default 24h) schedules the archive message for deletion
        archived = archive.send.return_value
        assert archived.id in mm.scheduled_deletions, mm.scheduled_deletions
        # The archive DB calls are awaited: the row exists, and expiring the message drops it,
        # so the URL can be archived again later
        assert (await db.get_archived_video(URL, GUILD))["discord_url"] == "https://cdn.example/v.mp4"
        # Rows are per guild: another guild archiving the same URL doesn't touch this one
        await db.add_archived_video(URL, "https://cdn.example/other.mp4", 1, 2, GUILD + 1)
        assert await db.get_archived_video(URL, GUILD + 1) and await db.is_url_archived(URL, GUILD)
        await schedule.call_args.args[1]()
        archived.delete.assert_awaited_once()
        assert not await db.is_url_archived(URL, GUILD)
        assert await db.is_url_archived(URL, GUILD + 1)

        # #3: real counts, not the error default
        await wait_for(lambda: qm.get_queue_status(GUILD)["completed"] == 1, "completed count")
        status = qm.get_queue_status(GUILD)
        assert (status["pending"], status["processing"], status["failed"]) == (0, 0, 0), status
        assert status["state"] == QueueState.RUNNING.value, status
        assert status["metrics"]["total_processed"] == 1, status["metrics"]
        assert not os.path.exists(video), "downloaded file not cleaned up"

        ctx = MagicMock(guild=guild, send=AsyncMock())
        await processor.show_queue_details(ctx)
        assert isinstance(ctx.send.call_args.kwargs.get("embed"), discord.Embed), ctx.send.call_args

        task = qm._processing_task
        await videoarchiver.teardown(bot)
        assert task.done(), "queue processing still running after unload"
        assert "on_message" not in bot.extra_events or not bot.extra_events["on_message"]

    logging.getLogger().removeHandler(errors)
    assert not errors.records, "errors logged:\n" + "\n".join(
        f"{r.name}: {r.getMessage()}" for r in errors.records)
    print("videoarchiver pipeline ok")


if __name__ == "__main__":
    asyncio.run(main())
