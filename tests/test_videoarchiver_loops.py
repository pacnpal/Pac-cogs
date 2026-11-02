"""Self-check: VideoArchiver background loops run without logging errors. Needs Red-DiscordBot installed.

Runs the queue monitor, cleanup, maintenance/stats and persistence paths plus the cog's
health monitors for a few cycles with sleeps capped short, and fails on any ERROR record.
Then reloads the cog to check the persisted queue round-trips.

Run from the repo root: python tests/test_videoarchiver_loops.py
"""
import asyncio
import logging
import sys
import tempfile
import types
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from redbot.core import _drivers, data_manager
from redbot.core._cli import parse_cli_flags
from redbot.core.bot import Red

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import videoarchiver  # noqa: E402
from videoarchiver.database.video_archive_db import VideoArchiveDB  # noqa: E402
from videoarchiver.core.c_types import QueueState  # noqa: E402
from videoarchiver.ffmpeg.ffmpeg_manager import FFmpegManager  # noqa: E402
from videoarchiver.queue.manager import EnhancedVideoQueueManager, QueueConfig  # noqa: E402

LOOP_MODULES = ("queue.manager", "queue.monitoring", "queue.cleanup", "core.base", "processor.core")
_real_sleep = asyncio.sleep


def fast_asyncio():
    """asyncio stand-in whose sleep() is capped, so hour-long loop intervals pass in ms"""
    fake = types.SimpleNamespace(**vars(asyncio))
    fake.sleep = lambda delay, *a, **k: _real_sleep(min(delay, 0.02), *a, **k)
    return fake


class ErrorCollector(logging.Handler):
    def __init__(self):
        super().__init__(logging.ERROR)
        self.records = []

    def emit(self, record):
        self.records.append(record)


async def wait_ready(bot):
    await videoarchiver.setup(bot)
    cog = bot.get_cog("VideoArchiver")
    await asyncio.wait_for(cog.ready.wait(), timeout=30)
    return cog


async def main():
    data_manager.basic_config = {"DATA_PATH": tempfile.mkdtemp(), "COG_PATH_APPEND": "cogs",
                                 "CORE_PATH_APPEND": "core", "STORAGE_TYPE": "JSON", "STORAGE_DETAILS": {}}
    data_manager.instance_name = "test"
    await _drivers.get_driver_class().initialize(**data_manager.storage_details())
    bot = Red(cli_flags=parse_cli_flags(["test"]), description="test")
    bot.is_owner = AsyncMock(return_value=False)

    errors = ErrorCollector()
    logging.getLogger().addHandler(errors)
    with ExitStack() as stack:
        stack.enter_context(patch("videoarchiver.core.component_manager.FFmpegManager",
                                  lambda: MagicMock(spec=FFmpegManager)))
        stack.enter_context(patch("videoarchiver.update_checker.UpdateChecker.update_yt_dlp",
                                  AsyncMock(return_value=(True, "stub"))))
        # The queued item's guild has no downloader; keep it queued (processing is covered
        # by test_videoarchiver_pipeline.py)
        stack.enter_context(patch("videoarchiver.queue.processor.QueueProcessor.start_processing",
                                  AsyncMock()))
        for mod in LOOP_MODULES:
            stack.enter_context(patch(f"videoarchiver.{mod}.asyncio", fast_asyncio()))

        cog = await wait_ready(bot)
        qm = cog.queue_manager
        assert qm.persistence is not None
        cog.db = db = VideoArchiveDB(cog.data_path)  # as `archivedb enable` would
        assert await qm.add_to_queue("https://example.com/v.mp4", 11, 22, 33, 44)
        stats_before = qm.stats.uptime

        await _real_sleep(1.0)  # many cycles of every loop

        status = cog.status_tracker.health_checks
        for check in ("queue_health", "processor_health", "database_health", "event_health"):
            assert check in status, f"{check} never recorded"
        assert qm.stats.uptime > stats_before, "stats loop never ran"
        assert qm.cleaner.tracker.history, "cleanup loop never ran"
        assert qm.metrics_manager.performance.peak_memory_usage > 0, "monitor never ran a health check"
        assert Path(qm.persistence.persistence_path).exists(), "queue state never persisted"

        await videoarchiver.teardown(bot)
        db.close()

        # Persisted queue survives a reload
        cog = await wait_ready(bot)
        queue = await cog.queue_manager.state_manager.get_queue()
        assert [i.url for i in queue] == ["https://example.com/v.mp4"], queue
        await _real_sleep(0.2)

        # force_stop (used when cleanup times out) is sync and leaves no loop running
        qm = cog.queue_manager
        tasks = [qm._maintenance_task, qm._stats_task, qm.monitor._monitoring_task,
                 qm.cleaner._cleanup_task]
        assert all(t and not t.done() for t in tasks)
        assert qm.force_stop() is None
        await _real_sleep(0.05)
        assert all(t.done() for t in tasks), tasks
        assert qm.state == QueueState.STOPPED
        await bot.remove_cog("VideoArchiver")

    try:
        EnhancedVideoQueueManager(QueueConfig(persistence_path=None))
        raise AssertionError("persistence without a path should be rejected")
    except ValueError:
        pass

    logging.getLogger().removeHandler(errors)
    assert not errors.records, "errors logged:\n" + "\n".join(
        f"{r.name}: {r.getMessage()}" for r in errors.records)
    print("videoarchiver loops ok")


if __name__ == "__main__":
    asyncio.run(main())
