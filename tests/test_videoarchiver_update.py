"""Self-check for the daily yt-dlp updater. Needs Red-DiscordBot and yt-dlp.

Run from the repo root: python tests/test_videoarchiver_update.py
"""
import asyncio
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import yt_dlp  # noqa: E402
from videoarchiver import update_checker  # noqa: E402
from videoarchiver.update_checker import UpdateChecker, reload_yt_dlp  # noqa: E402


def fake_pip(returncode=0):
    proc = MagicMock(returncode=returncode)
    proc.communicate = AsyncMock(return_value=(b"", b"boom"))
    return AsyncMock(return_value=proc)


async def main():
    # Hot-swap rebinds yt_dlp in our modules and leaves others alone
    ours = types.ModuleType("videoarchiver._fake")
    ours.yt_dlp = yt_dlp
    theirs = types.ModuleType("elsewhere")
    theirs.yt_dlp = yt_dlp
    sys.modules.update({"videoarchiver._fake": ours, "elsewhere": theirs})
    old = yt_dlp
    reload_yt_dlp()
    assert sys.modules["yt_dlp"] is not old
    assert ours.yt_dlp is sys.modules["yt_dlp"]
    assert theirs.yt_dlp is old

    checker = UpdateChecker()
    with patch.object(update_checker, "reload_yt_dlp") as reload, \
         patch("asyncio.create_subprocess_exec", fake_pip()) as pip:
        # New version installed: swap it in
        with patch.object(UpdateChecker, "_current_version", side_effect=["1", "2"]):
            ok, msg = await checker.update_yt_dlp()
        assert ok and "1 -> 2" in msg, msg
        reload.assert_called_once()
        assert "--upgrade" in pip.call_args.args and "yt-dlp" in pip.call_args.args

        # Already latest: nothing to swap
        reload.reset_mock()
        with patch.object(UpdateChecker, "_current_version", return_value="2"):
            ok, msg = await checker.update_yt_dlp()
        assert ok and "up to date" in msg
        reload.assert_not_called()

    with patch("asyncio.create_subprocess_exec", fake_pip(returncode=1)):
        ok, msg = await checker.update_yt_dlp()
    assert not ok and "boom" in msg

    # start() updates right away, then sleeps a day; stop() cancels cleanly
    with patch.object(UpdateChecker, "update_yt_dlp", AsyncMock(return_value=(True, "ok"))) as upd:
        await checker.start()
        await asyncio.sleep(0.05)
        upd.assert_awaited_once()
        await checker.stop()
    assert checker._task is None
    print("ok")


if __name__ == "__main__":
    asyncio.run(main())
