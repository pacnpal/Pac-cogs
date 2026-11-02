"""Self-check for processor/: URL extraction, temp-file cleanup on failed upload, archived reaction.

Run from the repo root: python tests/test_videoarchiver_processor.py
"""
import asyncio
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import discord

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from videoarchiver.processor.constants import REACTIONS  # noqa: E402
from videoarchiver.processor.queue_handler import QueueHandler  # noqa: E402
from videoarchiver.processor.reactions import handle_archived_reaction  # noqa: E402
from videoarchiver.processor.url_extractor import URLExtractor  # noqa: E402

ID = "dQw4w9WgXcQ"
ACCEPT = {
    f"<https://www.youtube.com/watch?v={ID}>": f"https://www.youtube.com/watch?v={ID}",
    f"||https://youtu.be/{ID}||": f"https://youtu.be/{ID}",
    f"https://youtube.com/shorts/{ID}?feature=share": None,
    f"https://m.youtube.com/watch?v={ID}": None,
    f"https://www.youtube.com/watch?app=desktop&v={ID}": None,
    "https://player.vimeo.com/video/123456": None,
    "https://mobile.twitter.com/u/status/123": None,
    "https://twitter.com/i/web/status/123": None,
    "(https://example.com/a.mp4).": "https://example.com/a.mp4",
}
REJECT = [f"https://notyoutube.com/watch?v={ID}", "https://www.youtube.com/@someone"]


def msg(content, mid):
    m = MagicMock()
    m.id, m.content, m.attachments = mid, f"look {content} ok", []
    return m


async def main():
    ex = URLExtractor()
    for i, (text, want) in enumerate(ACCEPT.items()):
        got = [u.url for u in await ex.extract_urls(msg(text, i))]
        assert got == [want or text], (text, got)
    for i, text in enumerate(REJECT, 100):
        assert not await ex.extract_urls(msg(text, i)), text

    # A failed upload still deletes the downloaded file (process_video never gets the path)
    fd, video = tempfile.mkstemp(suffix=".mp4")
    os.close(fd)
    qh = QueueHandler(MagicMock(), MagicMock(), MagicMock(), {})
    qh._download_video = AsyncMock(return_value=(True, video, ""))
    qh._archive_video = AsyncMock(side_effect=RuntimeError("413 Payload Too Large"))
    item = MagicMock(url="u", guild_id=1)
    try:
        await qh._process_video_file(MagicMock(), MagicMock(), item, None)
        raise AssertionError("expected the upload error")
    except RuntimeError:
        pass
    assert not os.path.exists(video), "temp file left behind after failed upload"

    assert [QueueHandler._progress_step(p) for p in (0, 20, 21, 80, 99, 100)] == [0, 0, 1, 3, 4, 5]
    assert isinstance(REACTIONS["numbers"], list)

    # 🔄 on a message whose first reaction is the bot's ✅ still answers
    m = MagicMock(spec=discord.Message)
    m.content = f"look <https://youtu.be/{ID}>."
    m.reactions = [MagicMock(emoji=REACTIONS["success"]), MagicMock(emoji=REACTIONS["archived"])]
    m.reply = AsyncMock()
    m.guild.id = 42
    db = MagicMock(get_archived_video=AsyncMock(return_value={"discord_url": "https://cdn/x.mp4"}))
    await handle_archived_reaction(m, None, db)  # get_user() cache miss -> None
    db.get_archived_video.assert_awaited_with(f"https://youtu.be/{ID}", 42)
    m.reply.assert_awaited_once()
    print("videoarchiver processor ok")


if __name__ == "__main__":
    asyncio.run(main())
