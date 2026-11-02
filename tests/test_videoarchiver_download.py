"""Self-check for videoarchiver DownloadManager.download_video. No network, no real ffmpeg.

Run from the repo root: python tests/test_videoarchiver_download.py
"""
import asyncio
import os
import stat
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import yt_dlp

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from videoarchiver.utils.download_core import DownloadCore  # noqa: E402
from videoarchiver.utils.download_manager import DownloadManager  # noqa: E402
from videoarchiver.utils.file_operations import FileOperations  # noqa: E402

MB = 1024 * 1024


def fake_ytdl(size=None, error=None, playlist=False):
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
            entry = {"requested_downloads": [{"filepath": path}]}
            return {"_type": "playlist", "entries": [entry]} if playlist else entry
    return FakeYDL


def slow_ytdl(started, stopped):
    """YoutubeDL stand-in that keeps 'downloading' a .part file until a progress hook raises."""
    class SlowYDL(fake_ytdl()):
        def extract_info(self, url, download):
            try:
                part = Path(self.opts["paths"]["home"], "clip.mp4.part")
                for i in range(500):  # ~5s, then give up so a broken cancel fails the test
                    part.write_bytes(b"x" * i)
                    started.set()
                    for hook in self.opts["progress_hooks"]:
                        hook({"status": "downloading", "downloaded_bytes": i, "total_bytes": 500})
                    time.sleep(0.01)
            finally:
                stopped.set()
    return SlowYDL


def make_manager(tmp, max_mb, fmt="mp4"):
    # Fake ffmpeg: logs its args, prints one progress line, writes a 1KB output file (last arg).
    ffmpeg = tmp / "ffmpeg"
    # It fails any h264_nvenc encode, like a GPU host whose NVENC is broken.
    ffmpeg.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$0.log"\ncase "$*" in *h264_nvenc*) exit 1;; esac\n'
                      'for last; do :; done\necho out_time_ms=500000\nhead -c 1024 /dev/zero > "$last"\n')
    ffmpeg.chmod(ffmpeg.stat().st_mode | stat.S_IEXEC)
    ffmpeg_mgr = MagicMock()
    ffmpeg_mgr.get_ffmpeg_path.return_value = str(ffmpeg)
    ffmpeg_mgr.get_ffprobe_path.return_value = "/x/ffprobe"
    ffmpeg_mgr.gpu_info = {"nvidia": False, "amd": False, "intel": False}
    ffmpeg_mgr.get_compression_params.return_value = {"c:v": "libx264", "crf": "23"}
    ffmpeg_mgr.cpu_cores = 2
    ffmpeg_mgr.analyze_video.return_value = {"duration": 1.0, "bitrate": 50_000_000}
    downloads = tmp / "downloads"
    return DownloadManager(str(downloads), fmt, 720, max_mb, ffmpeg_mgr=ffmpeg_mgr), downloads, ffmpeg


def patched(ydl):
    return patch.object(yt_dlp, "YoutubeDL", ydl), \
        patch.object(FileOperations, "verify_video_file", lambda self, path, probe: os.path.getsize(path) > 0), \
        patch.object(FileOperations, "get_video_duration", lambda self, path, probe: 1.0)


def run(dm, url, ydl):
    progress = []
    p1, p2, p3 = patched(ydl)
    with p1, p2, p3:
        def on_progress(pct):  # must be called on the event loop thread, not yt-dlp's
            assert threading.current_thread() is threading.main_thread(), "progress off the loop"
            progress.append(pct)
        result = asyncio.run(dm.download_video(url, progress_callback=on_progress))
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
    assert os.path.basename(path).startswith("clip [abc]_dl") and path.endswith(".mp4"), path
    assert os.path.getsize(path) == 1000, path
    assert os.listdir(downloads) == [os.path.basename(path)], os.listdir(downloads)
    assert progress == [50.0], progress
    assert not Path(f"{ffmpeg}.log").exists(), "compressed a file under the limit"

    # Over the limit: compressed through CompressionManager + ffmpeg, original removed.
    tmp = Path(tempfile.mkdtemp())
    dm, downloads, ffmpeg = make_manager(tmp, 1)
    (ok, path, err), progress = run(dm, "https://example.com/b", fake_ytdl(size=2 * MB))
    assert (ok, err) == (True, ""), err
    assert path.endswith("_compressed.mp4") and os.path.getsize(path) == 1024, path
    assert os.listdir(downloads) == [os.path.basename(path)], os.listdir(downloads)
    args = Path(f"{ffmpeg}.log").read_text().splitlines()
    assert args[args.index("-i") + 1] == path.replace("_compressed.mp4", ".mp4") and "libx264" in args, args
    assert progress == [50.0, 50.0], progress  # download hook, then ffmpeg out_time_ms

    # Multi-video post: yt-dlp is capped to one item and returns a playlist holding it.
    tmp = Path(tempfile.mkdtemp())
    dm, downloads, _ = make_manager(tmp, 8)
    assert dm.ydl_opts["playlist_items"] == "1"
    (ok, path, err), _ = run(dm, "https://example.com/p", fake_ytdl(size=1000, playlist=True))
    assert (ok, err) == (True, "") and os.path.getsize(path) == 1000, err

    # yt-dlp error: clean failure, partial files gone.
    tmp = Path(tempfile.mkdtemp())
    dm, downloads, _ = make_manager(tmp, 8)
    (ok, path, err), _ = run(dm, "https://example.com/c", fake_ytdl(error="ERROR: Video unavailable"))
    assert (ok, path) == (False, "") and "Video unavailable" in err, err
    assert os.listdir(downloads) == [], os.listdir(downloads)

    # Cancel mid-download (queue_handler's wait_for timeout): yt-dlp stops, then the temp dir goes.
    tmp = Path(tempfile.mkdtemp())
    dm, downloads, _ = make_manager(tmp, 8)
    dm.CANCEL_GRACE = 1  # well under slow_ytdl's ~5s, so only a working cancel stops it in time
    started, stopped = threading.Event(), threading.Event()

    async def cancel_midway():
        task = asyncio.create_task(dm.download_video("https://example.com/d"))
        await asyncio.to_thread(started.wait, 5)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError("download_video swallowed the cancel")
        assert stopped.is_set(), "yt-dlp worker still running after cancel"
        assert os.listdir(downloads) == [], os.listdir(downloads)

    p1, p2, p3 = patched(slow_ytdl(started, stopped))
    with p1, p2, p3:
        asyncio.run(cancel_midway())
    asyncio.run(dm.cleanup())

    # Cancel during verification: the finished file is outside the temp dir now, so it must
    # still be deleted (once ffprobe is done with it).
    tmp = Path(tempfile.mkdtemp())
    dm, downloads, _ = make_manager(tmp, 8)
    probing, release = threading.Event(), threading.Event()

    def slow_verify(self, path, probe):
        probing.set()
        release.wait(5)
        return True

    async def cancel_in_verify():
        task = asyncio.create_task(dm.download_video("https://example.com/v"))
        await asyncio.to_thread(probing.wait, 5)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert os.listdir(downloads), "file deleted while ffprobe still had it"
        release.set()
        for _ in range(100):
            if not os.listdir(downloads):
                break
            await asyncio.sleep(0.02)
        assert os.listdir(downloads) == [], os.listdir(downloads)

    p1, _, p3 = patched(fake_ytdl(size=1000))
    with p1, p3, patch.object(FileOperations, "verify_video_file", slow_verify):
        asyncio.run(cancel_in_verify())
    asyncio.run(dm.cleanup())

    # Cancel during compression: ffmpeg is killed and reaped before the files go away.
    tmp = Path(tempfile.mkdtemp())
    dm, downloads, ffmpeg = make_manager(tmp, 1)
    ffmpeg.write_text("#!/bin/sh\nexec sleep 30\n")
    src = tmp / "big.mp4"
    src.write_bytes(b"x" * 2 * MB)

    async def cancel_in_compress():
        cm = dm.compression_manager
        task = asyncio.create_task(cm.compress_video(str(src), str(tmp / "out.mp4"), None))
        for _ in range(250):
            if cm._active_processes:
                break
            await asyncio.sleep(0.02)
        procs = list(cm._active_processes)
        assert procs, "compression never started ffmpeg"
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert all(p.returncode is not None for p in procs), "ffmpeg still running after cancel"

    p1, p2, p3 = patched(fake_ytdl(size=1000))
    with p1, p2, p3:
        asyncio.run(cancel_in_compress())
    asyncio.run(dm.cleanup())

    # Two guilds archive the same video at once: each gets its own file.
    tmp = Path(tempfile.mkdtemp())
    dm, downloads, _ = make_manager(tmp, 8)

    async def twice():
        return await asyncio.gather(*(dm.download_video("https://example.com/e") for _ in range(2)))

    p1, p2, p3 = patched(fake_ytdl(size=1000))
    with p1, p2, p3:
        (ok1, path1, _), (ok2, path2, _) = asyncio.run(twice())
    asyncio.run(dm.cleanup())
    assert ok1 and ok2 and path1 != path2, (path1, path2)
    assert sorted(os.listdir(downloads)) == sorted(map(os.path.basename, (path1, path2)))

    # Format string per container, quality cap kept.
    fmts = {f: make_manager(Path(tempfile.mkdtemp()), 8, f)[0].ydl_opts["format"] for f in ("mp4", "webm", "mkv")}
    assert fmts["webm"] == ("bestvideo[ext=webm][height<=720]+bestaudio[ext=webm]/best[ext=webm][height<=720]"
                            "/bestvideo[height<=720]+bestaudio/best[height<=720]/best"), fmts["webm"]
    # CPU encodes never get the NVENC-only p5/p6 presets
    from videoarchiver.ffmpeg.encoder_params import EncoderParams
    cpu = EncoderParams(4, {"nvidia": False, "amd": False, "intel": False})
    for ctype in cpu.QUALITY_PRESETS:
        with patch.object(cpu, "_detect_content_type", return_value=ctype):
            assert cpu._get_content_specific_params({}).get("preset") not in cpu.NVENC_PRESETS, ctype
    assert fmts["mp4"].startswith("bv*[height<=720][ext=mp4]+ba[ext=m4a]/"), fmts["mp4"]
    assert "ext=" not in fmts["mkv"] and "height<=720" in fmts["mkv"], fmts["mkv"]

    # GPU host: NVENC fails, the CPU retry uses libx264 params, not the NVENC preset.
    tmp = Path(tempfile.mkdtemp())
    dm, downloads, ffmpeg = make_manager(tmp, 1)
    dm.ffmpeg_mgr.gpu_info = {"nvidia": True, "amd": False, "intel": False}
    dm.ffmpeg_mgr.get_compression_params.return_value = {"c:v": "h264_nvenc", "preset": "p5", "rc:v": "vbr"}
    (ok, path, err), _ = run(dm, "https://example.com/f", fake_ytdl(size=2 * MB))
    assert (ok, err) == (True, ""), err
    args = Path(f"{ffmpeg}.log").read_text().splitlines()
    assert args[args.index("-c:v") + 1] == "libx264" and "-rc:v" not in args, args
    assert args[args.index("-preset") + 1] in ("ultrafast", "superfast", "veryfast", "faster", "fast",
                                               "medium", "slow", "slower", "veryslow"), args
    print("ok")


if __name__ == "__main__":
    main()
