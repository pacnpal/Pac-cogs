"""Self-check for videoarchiver FFmpeg setup (#23) and ProgressTracker callers (#25).

Run from the repo root: python tests/test_videoarchiver_ffmpeg_progress.py
"""
import asyncio
import socket
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
BIN = ROOT / "videoarchiver" / "bin"


def no_network(*args, **kwargs):
    raise AssertionError("network access during import")


def main():
    # 23: importing the ffmpeg package must not locate/download FFmpeg.
    assert not BIN.exists(), f"remove {BIN} before running"
    with patch.object(socket.socket, "connect", no_network), patch.object(socket, "create_connection", no_network):
        import videoarchiver.ffmpeg as vf
        from videoarchiver.utils import download_manager as dm_mod, get_active_downloads
        from videoarchiver.utils.progress_tracker import ProgressTracker
    assert not BIN.exists(), "import created videoarchiver/bin"
    assert not hasattr(vf, "ffmpeg"), "module-level FFmpeg instance still built at import"

    # 23: FFmpegManager() sets up binaries first, then runs GPU detection on the real path.
    from videoarchiver.ffmpeg import ffmpeg_manager as fm
    tmp = Path(tempfile.mkdtemp())
    (tmp / "ffmpeg").touch()
    (tmp / "ffprobe").touch()
    calls = []
    paths = {"ffmpeg": tmp / "ffmpeg", "ffprobe": tmp / "ffprobe"}
    with patch.object(fm.BinaryManager, "initialize_binaries", lambda self, gpu: calls.append("bin") or paths), \
         patch.object(fm.GPUDetector, "detect_gpu", lambda self: calls.append(self.ffmpeg_path) or {"nvidia": False, "amd": False, "intel": False}):
        mgr = fm.FFmpegManager()
    assert calls == ["bin", tmp / "ffmpeg"], calls
    assert mgr.video_analyzer.ffprobe_path == tmp / "ffprobe"
    assert not BIN.exists()

    # 25: download_manager progress path against the real ProgressTracker.
    tracker = ProgressTracker()
    assert tracker is dm_mod.progress_tracker
    ffmpeg_mgr = MagicMock()
    ffmpeg_mgr.get_ffmpeg_path.return_value = "/x/ffmpeg"
    ffmpeg_mgr.get_ffprobe_path.return_value = "/x/ffprobe"
    dm = dm_mod.DownloadManager(tempfile.mkdtemp(), "mp4", 720, 8, ffmpeg_mgr=ffmpeg_mgr)
    url = "https://example.com/v"
    other = "https://example.com/other"
    tracker.update_download_progress(other, {"percent": 10})

    async def fake_download(u, cb):
        assert tracker.get_download_progress(u)["active"] is True
        assert get_active_downloads().keys() == {url, other}
        dm._progress_hook({"status": "downloading", "downloaded_bytes": 50, "total_bytes": 100,
                           "info_dict": {"original_url": u}})
        return False, "", "boom"

    dm._safe_download = AsyncMock(side_effect=fake_download)
    assert asyncio.run(dm.download_video(url)) == (False, "", "boom")
    p = tracker.get_download_progress(url)
    assert p["percent"] == 50 and p["total_bytes"] == 100, p
    assert p["active"] is False, p
    assert get_active_downloads().keys() == {other}

    asyncio.run(dm.cleanup())
    assert tracker.get_download_progress(other)["percent"] == 10, "cleanup wiped other downloads"
    print("ok")


if __name__ == "__main__":
    main()
