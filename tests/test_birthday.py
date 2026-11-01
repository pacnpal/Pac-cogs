"""Self-check for the Birthday cog. Needs Red-DiscordBot installed.

Run from the repo root: python tests/test_birthday.py
"""
import asyncio
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import discord
from redbot.core import _drivers, data_manager
from redbot.core._cli import parse_cli_flags
from redbot.core.bot import Red

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from birthday.birthday import Birthday, next_midnight, remove_at, render  # noqa: E402


def fake_guild():
    guild = MagicMock(spec=discord.Guild, id=1, unavailable=False)
    guild.name = "Test Server"
    role = MagicMock(spec=discord.Role, id=10, guild=guild, managed=False)
    role.name = "Birthday"
    role.is_default.return_value = False
    role.__ge__.return_value = False  # below the bot's top role
    guild.me = MagicMock(spec=discord.Member)
    guild.me.guild_permissions.manage_roles = True
    channel = MagicMock(spec=discord.TextChannel)
    channel.send = AsyncMock()
    members = {}

    def member(member_id, manage_roles=False):
        m = MagicMock(spec=discord.Member, id=member_id, guild=guild, bot=False, roles=[])
        m.display_name = f"user{{name}}{member_id}"
        m.mention = f"<@{member_id}>"
        m.guild_permissions.manage_roles = manage_roles
        m.add_roles = AsyncMock(side_effect=lambda r, **_: m.roles.append(r))
        m.remove_roles = AsyncMock(side_effect=lambda r, **_: m.roles.remove(r))
        members[member_id] = m
        return m

    guild.get_role.side_effect = {10: role}.get
    guild.get_member.side_effect = members.get
    guild.get_channel.return_value = None
    return guild, role, channel, member


async def main():
    # Pure helpers
    assert remove_at({"remove_at": "2026-11-02T00:00:00-05:00"}) == datetime(2026, 11, 2, 5, tzinfo=ZoneInfo("UTC")).timestamp()
    assert remove_at({"remove_at": 123}) == 123
    ny = ZoneInfo("America/New_York")
    assert next_midnight(ny, datetime(2026, 10, 31, 15, tzinfo=ny)).isoformat() == "2026-11-01T00:00:00-04:00"
    assert next_midnight(ny, datetime(2026, 11, 1, 15, tzinfo=ny)).isoformat() == "2026-11-02T00:00:00-05:00"

    data_manager.basic_config = {"DATA_PATH": tempfile.mkdtemp(), "COG_PATH_APPEND": "cogs",
                                 "CORE_PATH_APPEND": "core", "STORAGE_TYPE": "JSON", "STORAGE_DETAILS": {}}
    data_manager.instance_name = "test"
    await _drivers.get_driver_class().initialize(**data_manager.storage_details())
    bot = Red(cli_flags=parse_cli_flags(["test"]), description="test")
    bot.is_owner = AsyncMock(return_value=False)
    cog = Birthday(bot)
    await bot.add_cog(cog)
    cog.expiry_loop.cancel()

    guild, role, channel, member = fake_guild()
    bot.get_guild = {1: guild}.get
    conf = cog.config.guild(guild)
    await conf.birthday_role.set(role.id)
    mod, alice, bob = member(1, manage_roles=True), member(2), member(3)

    assert "permission" in await cog.give(alice, bob, channel)
    assert "Birthday role given" in await cog.give(mod, alice, channel)
    assert "Birthday role given" in await cog.give(mod, bob, channel)
    assert "already celebrating" in await cog.give(mod, alice, channel)
    assert role in alice.roles and role in bob.roles
    sent = channel.send.call_args.args[0]
    assert "<@3>" in sent, sent
    assert render("{name} {mention}", bob) == "user{name}3 <@3>"  # placeholders in names aren't re-expanded

    # Two members in one guild expire independently (used to cancel each other).
    await conf.scheduled_tasks.set_raw("2", "remove_at", value=0)
    await conf.scheduled_tasks.set_raw("3", "remove_at", value="2000-01-01T00:00:00+00:00")
    bob.remove_roles.side_effect = discord.HTTPException(MagicMock(status=503), "down")
    await cog.expiry_loop.coro(cog)
    assert role not in alice.roles
    assert set(await conf.scheduled_tasks()) == {"3"}, "transient failure must be retried"
    bob.remove_roles.side_effect = lambda r, **_: bob.roles.remove(r)
    await cog.expiry_loop.coro(cog)
    assert role not in bob.roles and await conf.scheduled_tasks() == {}

    await cog.give(mod, alice, channel)
    assert "removed" in await cog.remove(mod, alice)
    assert await conf.scheduled_tasks() == {}

    await cog.give(mod, alice, channel)
    await cog.red_delete_data_for_user(requester="user", user_id=2)
    assert await conf.scheduled_tasks() == {}
    assert role not in alice.roles, "data deletion must not strand the role"

    # Race: expiry loop runs while add_roles is still waiting on Discord, with an entry that's
    # already due (command run right at midnight). The role must not be left on untracked.
    import birthday.birthday as bmod
    real_midnight = bmod.next_midnight
    bmod.next_midnight = lambda tz: datetime.now(tz)  # due immediately
    gate = asyncio.Event()

    async def slow_add(r, **_):
        await gate.wait()
        alice.roles.append(r)

    alice.add_roles = AsyncMock(side_effect=slow_add)
    give_task = asyncio.create_task(cog.give(mod, alice, channel))
    await asyncio.sleep(0)
    loop_task = asyncio.create_task(cog.expiry_loop.coro(cog))
    await asyncio.sleep(0.05)
    gate.set()
    await asyncio.gather(give_task, loop_task)
    await cog.expiry_loop.coro(cog)
    bmod.next_midnight = real_midnight
    tracked = str(alice.id) in await conf.scheduled_tasks()
    assert tracked or role not in alice.roles, "role stranded without an expiry entry"

    # Same race through manual removal: /removebirthday while add_roles is in flight.
    alice.roles.clear()
    gate.clear()
    give_task = asyncio.create_task(cog.give(mod, alice, channel))
    await asyncio.sleep(0)
    remove_task = asyncio.create_task(cog.remove(mod, alice))
    await asyncio.sleep(0.05)
    gate.set()
    await asyncio.gather(give_task, remove_task)
    tracked = str(alice.id) in await conf.scheduled_tasks()
    assert tracked or role not in alice.roles, "manual removal stranded the role"

    await bot.remove_cog("Birthday")
    print("birthday: all checks passed")


if __name__ == "__main__":
    asyncio.run(main())
