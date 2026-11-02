"""Self-check for videoarchiver DownloadManager.download_video. No network, no real ffmpeg.

Run from the repo root: python tests/test_videoarchiver_download.py
"""
import asyncio
import os
import stat
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import yt_dlp

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from videoarchiver.utils.download_core import DownloadCore  # noqa: E402
from videoarchiver.utils.download_manager import DownloadManager  # noqa: E402
from videoarchiver.utils.file_operations import FileOperations  # noqa: E402

MB = 1024 * 1024


def fake_ytdl(size=None, error=None):
    """YoutubeDL stand-in: writes a `size`-byte file into paths.home (or a .part then raises)."""
    class FakeYDL:
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def extract_info(self, url, download):
            assert download
            home = self.opts["paths"]["home"]
            if error:
                Path(home, "clip.mp4.part").write_bytes(b"partial")
                raise yt_dlp.utils.DownloadError(error)
            path = os.path.join(home, "clip [abc].mp4")
            with open(path, "wb") as f:
                f.truncate(size)
            for hook in self.opts["progress_hooks"]:
                hook({"status": "downloading", "downloaded_bytes": size // 2, "total_bytes": size,
                      "info_dict": {"original_url": url}})
                hook({"status": "finished", "filename": path})
            return {"requested_downloads": [{"filepath": path}]}
    return FakeYDL


def make_manager(tmp, max_mb):
    # Fake ffmpeg: logs its args, prints one progress line, writes a 1KB output file (last arg).
    ffmpeg = tmp / "ffmpeg"
    ffmpeg.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$0.log"\nfor last; do :; done\n'
                      'echo out_time_ms=500000\nhead -c 1024 /dev/zero > "$last"\n')
    ffmpeg.chmod(ffmpeg.stat().st_mode | stat.S_IEXEC)
    ffmpeg_mgr = MagicMock()
    ffmpeg_mgr.get_ffmpeg_path.return_value = str(ffmpeg)
    ffmpeg_mgr.get_ffprobe_path.return_value = "/x/ffprobe"
    ffmpeg_mgr.gpu_info = {"nvidia": False, "amd": False, "intel": False}
    ffmpeg_mgr.get_compression_params.return_value = {"c:v": "libx264", "crf": "23"}
    downloads = tmp / "downloads"
    return DownloadManager(str(downloads), "mp4", 720, max_mb, ffmpeg_mgr=ffmpeg_mgr), downloads, ffmpeg


def run(dm, url, ydl):
    progress = []
    with patch.object(yt_dlp, "YoutubeDL", ydl), \
         patch.object(FileOperations, "verify_video_file", lambda self, path, probe: os.path.getsize(path) > 0), \
         patch.object(FileOperations, "get_video_duration", lambda self, path, probe: 1.0):
        result = asyncio.run(dm.download_video(url, progress_callback=progress.append))
    asyncio.run(dm.cleanup())
    return result, progress


def main():
    assert DownloadCore is DownloadManager  # core/guild.py builds DownloadCore

    # Small file: downloaded, verified, moved out of its temp dir, returned as-is.
    tmp = Path(tempfile.mkdtemp())
    dm, downloads, ffmpeg = make_manager(tmp, 8)
    assert "max_filesize" not in dm.ydl_opts, "yt-dlp would refuse files that we could compress"
    (ok, path, err), progress = run(dm, "https://example.com/a", fake_ytdl(size=1000))
    assert (ok, err) == (True, ""), err
    assert path == str(downloads / "clip [abc].mp4") and os.path.getsize(path) == 1000, path
    assert os.listdir(downloads) == ["clip [abc].mp4"], os.listdir(downloads)
    assert progress == [50.0], progress
    assert not Path(f"{ffmpeg}.log").exists(), "compressed a file under the limit"

    # Over the limit: compressed through CompressionManager + ffmpeg, original removed.
    tmp = Path(tempfile.mkdtemp())
    dm, downloads, ffmpeg = make_manager(tmp, 1)
    (ok, path, err), progress = run(dm, "https://example.com/b", fake_ytdl(size=2 * MB))
    assert (ok, err) == (True, ""), err
    assert path == str(downloads / "clip [abc]_compressed.mp4") and os.path.getsize(path) == 1024, path
    assert os.listdir(downloads) == ["clip [abc]_compressed.mp4"], os.listdir(downloads)
    args = Path(f"{ffmpeg}.log").read_text().splitlines()
    assert args[args.index("-i") + 1] == str(downloads / "clip [abc].mp4") and "libx264" in args, args
    assert progress == [50.0, 50.0], progress  # download hook, then ffmpeg out_time_ms

    # yt-dlp error: clean failure, partial files gone.
    tmp = Path(tempfile.mkdtemp())
    dm, downloads, _ = make_manager(tmp, 8)
    (ok, path, err), _ = run(dm, "https://example.com/c", fake_ytdl(error="ERROR: Video unavailable"))
    assert (ok, path) == (False, "") and "Video unavailable" in err, err
    assert os.listdir(downloads) == [], os.listdir(downloads)
    print("ok")


if __name__ == "__main__":
    main()
