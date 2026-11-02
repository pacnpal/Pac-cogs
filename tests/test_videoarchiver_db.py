"""Self-check for the VideoArchiver archive DB schema: reopening, v1->v2 migration, rollback.

Run from the repo root: python tests/test_videoarchiver_db.py
"""
import asyncio
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from videoarchiver.database.schema_manager import DatabaseSchemaManager as SM  # noqa: E402
from videoarchiver.database.video_archive_db import VideoArchiveDB  # noqa: E402

V1 = SM._get_migrations(SM.__new__(SM), 0)[0]


def v1_db(versions=(1,)):
    """A database as the v1 code left it, with one archived row for guild 10"""
    d = Path(tempfile.mkdtemp())
    with sqlite3.connect(d / "archived_videos.db") as c:
        c.executescript(V1)
        c.execute("CREATE TABLE schema_version (version INTEGER PRIMARY KEY, "
                  "last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP, migrations_applied TEXT)")
        c.executemany("INSERT INTO schema_version (version, migrations_applied) VALUES (?, '[]')",
                      [(v,) for v in versions])
        c.execute("INSERT INTO archived_videos (original_url, discord_url, message_id, channel_id, guild_id) "
                  "VALUES ('u', 'd', 1, 2, 10)")
    return d


def query(d, sql):
    with sqlite3.connect(d / "archived_videos.db") as c:
        return c.execute(sql).fetchall()


async def main():
    # Reopening used to raise a UNIQUE error: every open added a stray version-0 row
    d = Path(tempfile.mkdtemp())
    for _ in range(3):
        VideoArchiveDB(d)
    assert query(d, "SELECT version FROM schema_version") == [(SM.SCHEMA_VERSION,)]

    # A DB already broken that way (rows 0 and 1) recovers and migrates
    d = v1_db(versions=(0, 1))
    VideoArchiveDB(d)
    VideoArchiveDB(d)
    assert query(d, "SELECT version FROM schema_version") == [(2,)]

    # v1 -> v2 keeps rows, and two guilds can then hold the same URL
    d = v1_db()
    db = VideoArchiveDB(d)
    assert (await db.get_archived_video("u", 10))["discord_url"] == "d"
    assert await db.add_archived_video("u", "d2", 3, 4, 20)
    assert (await db.get_archived_video("u", 10))["discord_url"] == "d"
    assert (await db.get_archived_video("u", 20))["discord_url"] == "d2"
    await db.remove_archived_video("u", 20)
    assert await db.is_url_archived("u", 10) and not await db.is_url_archived("u", 20)

    # A migration that dies after DROP TABLE rolls back whole, and the next open retries it
    d = v1_db()
    real = SM._get_migrations
    SM._get_migrations = lambda self, v: [
        m.replace("ALTER TABLE archived_videos_v2", "SELECT no_such_fn(); ALTER TABLE archived_videos_v2")
        for m in real(self, v)
    ]
    try:
        VideoArchiveDB(d)
        raise AssertionError("broken migration should have failed")
    except AssertionError:
        raise
    except Exception:
        pass
    finally:
        SM._get_migrations = real
    tables = {r[0] for r in query(d, "SELECT name FROM sqlite_master WHERE type='table'")}
    assert "archived_videos" in tables and "archived_videos_v2" not in tables, tables
    assert query(d, "SELECT original_url FROM archived_videos") == [("u",)]
    assert query(d, "SELECT MAX(version) FROM schema_version") == [(1,)]
    assert (await VideoArchiveDB(d).get_archived_video("u", 10))["discord_url"] == "d"

    print("videoarchiver db ok")


if __name__ == "__main__":
    asyncio.run(main())
