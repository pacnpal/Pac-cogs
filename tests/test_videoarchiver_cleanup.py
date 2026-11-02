"""Self-check for VideoArchiver unload cleanup (issue #24).

The cog's processor/queue_manager/ffmpeg_mgr are read-only properties over the
component registry; cleanup must clear the registry instead of assigning None.

Run from the repo root: python tests/test_videoarchiver_cleanup.py
"""
import asyncio
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
# Load core.cleanup/core.lifecycle without the package __init__s (they pull in the whole bot).
for name in ("videoarchiver", "videoarchiver.core"):
    pkg = types.ModuleType(name)
    pkg.__path__ = [str(ROOT.joinpath(*name.split(".")))]
    sys.modules[name] = pkg

from videoarchiver.core import cleanup  # noqa: E402
from videoarchiver.core.lifecycle import LifecycleManager  # noqa: E402

NAMES = ("processor", "queue_manager", "ffmpeg_mgr")


class FakeCog:
    """Mirrors VideoArchiver: component properties with no setter."""

    processor = property(lambda self: self.component_manager._components.get("processor"))
    queue_manager = property(lambda self: self.component_manager._components.get("queue_manager"))
    ffmpeg_mgr = property(lambda self: self.component_manager._components.get("ffmpeg_mgr"))

    def __init__(self):
        self.component_manager = types.SimpleNamespace(
            _components={
                "processor": MagicMock(cleanup=AsyncMock(), force_cleanup=AsyncMock()),
                "queue_manager": MagicMock(cleanup=AsyncMock()),
                "ffmpeg_mgr": MagicMock(),
                "config_manager": MagicMock(),
            }
        )
        self.bot = object()
        self.ready = asyncio.Event()
        self.ready.set()
        self.components = {1: {"message_manager": MagicMock(cancel_all_deletions=AsyncMock())}}
        self.update_checker = None
        self.db = object()
        self._init_task = None
        self._cleanup_task = None
        self.download_path = None


def assert_cleared(cog):
    for name in NAMES:
        assert getattr(cog, name) is None, name
    assert "config_manager" in cog.component_manager._components  # untouched


async def main():
    with patch.object(cleanup.os, "system") as system:
        cog = FakeCog()
        processor = cog.processor
        ffmpeg = cog.ffmpeg_mgr
        await cleanup.cleanup_resources(cog)  # raised CleanupError before the fix
        assert_cleared(cog)
        processor.cleanup.assert_awaited_once()
        ffmpeg.kill_all_processes.assert_called_once()
        assert cog.components == {}  # guild components phase ran
        system.assert_called_once()  # system-wide ffmpeg kill ran
        assert not cog.ready.is_set()

        cog = FakeCog()
        await cleanup.force_cleanup_resources(cog)
        assert_cleared(cog)
        # References phase got past the component lines.
        assert cog.bot is None and cog.db is None and cog.components == {}

    cog = FakeCog()
    await LifecycleManager(cog)._cleanup_references()
    assert_cleared(cog)
    assert cog.components == {} and cog.db is None

    cleanup.clear_component(types.SimpleNamespace(), "processor")  # no registry: no-op
    print("ok")


if __name__ == "__main__":
    asyncio.run(main())
