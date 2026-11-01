import contextlib
import logging
import secrets
from datetime import datetime, time, timedelta, timezone
from typing import Optional, Union
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

import discord  # type: ignore
from discord.ext import tasks  # type: ignore
from redbot.core import Config, app_commands, commands  # type: ignore
from redbot.core.bot import Red  # type: ignore
from redbot.core.utils.chat_formatting import humanize_list, pagify  # type: ignore

log = logging.getLogger("red.pac-cogs.birthday")

TIMEZONES = sorted(available_timezones())

MESSAGES = (
    "🎉 Happy Birthday, {mention}! {cakes}",
    "🥳 It's {mention}'s birthday! Everybody make some noise! {cakes}",
    "🎈 Another lap around the sun for {mention}! {cakes}",
    "🎊 Hip hip hooray, it's {mention}'s special day! {cakes}",
    "🎁 {mention} just levelled up! Happy Birthday! {cakes}",
    "🕯️ Make a wish, {mention}! Happy Birthday! {cakes}",
)

NO_MENTIONS = discord.AllowedMentions.none()


def roll_cakes() -> str:
    """Random cake count: usually 1-5 cakes, sometimes pie, rarely a jackpot."""
    roll = secrets.randbelow(100)
    if roll == 0:
        return "🌟 LEGENDARY CAKE DROP! 🌟 " + "🎂" * 10
    if roll < 15:
        return "Sorry, out of cake today! Here's pie instead: 🥧"
    cakes = secrets.randbelow(5) + 1
    return f"Here's your cake{'s' if cakes > 1 else ''}: " + "🎂" * cakes


def render(template: str, member: discord.Member) -> str:
    # str.replace, not str.format: admins write the template, and format() allows attribute access.
    return (
        template.replace("{cakes}", roll_cakes())
        .replace("{server}", member.guild.name)
        .replace("{mention}", member.mention)
        .replace("{name}", member.display_name)
    )[:2000]


def remove_at(info: dict) -> float:
    """Expiry as a UTC timestamp. Older versions stored an ISO string."""
    value = info["remove_at"]
    if isinstance(value, (int, float)):
        return value
    dt = datetime.fromisoformat(value)
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).timestamp()


def next_midnight(tz: ZoneInfo, now: Optional[datetime] = None) -> datetime:
    now = now or datetime.now(tz)
    return datetime.combine(now.date() + timedelta(days=1), time.min, tzinfo=tz)


class Birthday(commands.Cog):
    """Give members a birthday role until midnight and throw them a party."""

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=5458102289)
        self.config.register_guild(
            birthday_role=None,
            allowed_roles=[],
            timezone="UTC",
            birthday_channel=None,
            message=None,
            scheduled_tasks={},
        )
        self.give_menu = app_commands.guild_only(
            app_commands.ContextMenu(name="Give Birthday Role", callback=self.give_menu_callback)
        )
        self.remove_menu = app_commands.guild_only(
            app_commands.ContextMenu(name="Remove Birthday Role", callback=self.remove_menu_callback)
        )

    async def cog_load(self) -> None:
        self.bot.tree.add_command(self.give_menu, override=True)
        self.bot.tree.add_command(self.remove_menu, override=True)
        self.expiry_loop.start()

    async def cog_unload(self) -> None:
        self.expiry_loop.cancel()
        self.bot.tree.remove_command(self.give_menu.name, type=self.give_menu.type)
        self.bot.tree.remove_command(self.remove_menu.name, type=self.remove_menu.type)

    async def red_delete_data_for_user(self, *, requester, user_id: int) -> None:
        for guild_id, data in (await self.config.all_guilds()).items():
            info = data["scheduled_tasks"].get(str(user_id))
            if info is None:
                continue
            # Take the role off first; without the entry the expiry loop would never remove it.
            guild = self.bot.get_guild(guild_id)
            if guild is not None:
                try:
                    await self.expire(guild, user_id, info["role_id"])
                except Exception:
                    log.exception("Failed to remove birthday role during data deletion in guild %s", guild_id)
            await self.config.guild_from_id(guild_id).scheduled_tasks.clear_raw(str(user_id))

    # ---- helpers -------------------------------------------------------

    async def get_tz(self, guild: discord.Guild) -> ZoneInfo:
        try:
            return ZoneInfo(await self.config.guild(guild).timezone())
        except (ZoneInfoNotFoundError, ValueError):
            return ZoneInfo("UTC")

    async def is_allowed(self, member: Union[discord.Member, discord.User]) -> bool:
        if not isinstance(member, discord.Member):
            return False
        if (
            member.guild_permissions.manage_roles
            or await self.bot.is_owner(member)
            or await self.bot.is_mod(member)
        ):
            return True
        allowed = await self.config.guild(member.guild).allowed_roles()
        return any(role.id in allowed for role in member.roles)

    def role_problem(self, role: discord.Role) -> Optional[str]:
        me = role.guild.me
        if role.is_default() or role.managed:
            return f"**{role.name}** is managed by Discord or an integration, so I can't assign it."
        if not me.guild_permissions.manage_roles:
            return "I need the **Manage Roles** permission."
        if role >= me.top_role:
            return f"My top role must be above **{role.name}** in the role list."
        return None

    async def announce(self, member: discord.Member, channel) -> bool:
        template = await self.config.guild(member.guild).message() or secrets.choice(MESSAGES)
        try:
            msg = await channel.send(
                render(template, member), allowed_mentions=discord.AllowedMentions(users=[member])
            )
        except (discord.HTTPException, AttributeError):
            return False
        with contextlib.suppress(discord.HTTPException):
            await msg.add_reaction("🎉")
        return True

    async def give(self, author, member: discord.Member, fallback_channel) -> str:
        guild = member.guild
        conf = self.config.guild(guild)
        if not await self.is_allowed(author):
            return "You don't have permission to use this command."
        if member.bot:
            return "Bots don't have birthdays... yet. 🤖"
        role = guild.get_role(await conf.birthday_role() or 0)
        if role is None:
            return "The birthday role isn't set or was deleted. An admin can set it with `birthdayset role`."
        if problem := self.role_problem(role):
            return problem

        scheduled = await conf.scheduled_tasks()
        if role in member.roles and str(member.id) in scheduled:
            ends = int(remove_at(scheduled[str(member.id)]))
            return f"{member.display_name} is already celebrating! The party ends <t:{ends}:R>."

        ends = int(next_midnight(await self.get_tz(guild)).timestamp())
        # Record first so a crash between the two steps can't leave the role on forever.
        await conf.scheduled_tasks.set_raw(str(member.id), value={"role_id": role.id, "remove_at": ends})
        try:
            await member.add_roles(role, reason=f"Birthday role given by {author} ({author.id})")
        except discord.HTTPException as e:
            await conf.scheduled_tasks.clear_raw(str(member.id))
            log.warning("Could not give birthday role in guild %s: %s", guild.id, e)
            return f"I couldn't give the birthday role: {e.text or e}"

        channel = guild.get_channel(await conf.birthday_channel() or 0) or fallback_channel
        reply = f"🎉 Birthday role given to {member.display_name}! It comes off <t:{ends}:R>."
        if not await self.announce(member, channel):
            reply += "\n⚠️ I couldn't post the announcement. Check my permissions in the birthday channel."
        return reply

    async def remove(self, author, member: discord.Member) -> str:
        conf = self.config.guild(member.guild)
        if not await self.is_allowed(author):
            return "You don't have permission to use this command."
        info = (await conf.scheduled_tasks()).get(str(member.id))
        role = member.guild.get_role(info["role_id"] if info else await conf.birthday_role() or 0)
        if role is None or role not in member.roles:
            await conf.scheduled_tasks.clear_raw(str(member.id))
            return f"{member.display_name} doesn't have the birthday role."
        try:
            await member.remove_roles(role, reason=f"Birthday role removed by {author} ({author.id})")
        except discord.HTTPException as e:
            return f"I couldn't remove the birthday role: {e.text or e}"
        await conf.scheduled_tasks.clear_raw(str(member.id))
        return f"Birthday role removed from {member.display_name}. Party's over! 🎈"

    async def expire(self, guild: discord.Guild, member_id: int, role_id: int) -> None:
        """Remove an expired birthday role. Transient errors propagate so the next tick retries."""
        role = guild.get_role(role_id)
        if role is not None:
            member = guild.get_member(member_id)
            if member is None:
                with contextlib.suppress(discord.NotFound):
                    member = await guild.fetch_member(member_id)
            if member is not None and role in member.roles:
                try:
                    await member.remove_roles(role, reason="Birthday is over")
                except (discord.Forbidden, discord.NotFound) as e:
                    log.warning("Giving up removing birthday role in guild %s: %s", guild.id, e)
        await self.config.guild(guild).scheduled_tasks.clear_raw(str(member_id))

    # ponytail: polls every minute, so roles come off up to ~60s after midnight.
    @tasks.loop(minutes=1)
    async def expiry_loop(self) -> None:
        now = datetime.now(timezone.utc).timestamp()
        for guild_id, data in (await self.config.all_guilds()).items():
            guild = self.bot.get_guild(guild_id)
            if guild is None or guild.unavailable:
                continue
            for member_id, info in data["scheduled_tasks"].items():
                try:
                    if remove_at(info) <= now:
                        await self.expire(guild, int(member_id), info["role_id"])
                except Exception:
                    log.exception("Failed to expire birthday role for %s in guild %s", member_id, guild_id)

    @expiry_loop.before_loop
    async def before_expiry_loop(self) -> None:
        await self.bot.wait_until_red_ready()

    # ---- context menus -------------------------------------------------

    async def give_menu_callback(self, interaction: discord.Interaction, member: discord.Member):
        await interaction.response.defer(ephemeral=True)
        await interaction.followup.send(
            await self.give(interaction.user, member, interaction.channel), ephemeral=True
        )

    async def remove_menu_callback(self, interaction: discord.Interaction, member: discord.Member):
        await interaction.response.defer(ephemeral=True)
        await interaction.followup.send(await self.remove(interaction.user, member), ephemeral=True)

    # ---- user commands -------------------------------------------------

    @commands.hybrid_command(name="birthday")
    @commands.guild_only()
    @app_commands.describe(member="The member who's celebrating")
    async def birthday(self, ctx: commands.Context, member: discord.Member):
        """Give someone the birthday role until midnight and announce it."""
        await ctx.defer(ephemeral=True)
        await ctx.send(await self.give(ctx.author, member, ctx.channel), ephemeral=True)

    @commands.hybrid_command(name="removebirthday")
    @commands.guild_only()
    @app_commands.describe(member="The member to remove the birthday role from")
    async def remove_birthday(self, ctx: commands.Context, member: discord.Member):
        """Remove the birthday role from someone early."""
        await ctx.defer(ephemeral=True)
        await ctx.send(await self.remove(ctx.author, member), ephemeral=True)

    @commands.hybrid_command(name="bdaycheck")
    @commands.guild_only()
    async def bdaycheck(self, ctx: commands.Context):
        """List who's celebrating right now and when their role comes off."""
        if not await self.is_allowed(ctx.author):
            return await ctx.send("You don't have permission to use this command.", ephemeral=True)
        scheduled = await self.config.guild(ctx.guild).scheduled_tasks()
        if not scheduled:
            return await ctx.send("Nobody is celebrating right now.", ephemeral=True)
        lines = [
            f"🎂 <@{member_id}>: role comes off <t:{int(remove_at(info))}:R>"
            for member_id, info in sorted(scheduled.items(), key=lambda kv: remove_at(kv[1]))
        ]
        for page in pagify("**Currently celebrating**\n" + "\n".join(lines)):
            await ctx.send(page, ephemeral=True, allowed_mentions=NO_MENTIONS)

    # ---- admin commands ------------------------------------------------

    @commands.hybrid_group(name="birthdayset")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    @app_commands.default_permissions(manage_guild=True)
    async def birthdayset(self, ctx: commands.Context):
        """Configure the Birthday cog."""

    @birthdayset.command(name="role")
    @commands.admin_or_permissions(manage_guild=True)
    @app_commands.describe(role="The role to give on birthdays")
    async def birthdayset_role(self, ctx: commands.Context, role: discord.Role):
        """Set the birthday role."""
        await self.config.guild(ctx.guild).birthday_role.set(role.id)
        msg = f"Birthday role set to **{role.name}**."
        if problem := self.role_problem(role):
            msg += f"\n⚠️ {problem}"
        await ctx.send(msg)

    @birthdayset.command(name="channel")
    @commands.admin_or_permissions(manage_guild=True)
    @app_commands.describe(channel="Where to announce birthdays (leave empty to use the command's channel)")
    async def birthdayset_channel(self, ctx: commands.Context, channel: Optional[discord.TextChannel] = None):
        """Set the announcement channel. Leave empty to announce wherever the command is used."""
        await self.config.guild(ctx.guild).birthday_channel.set(channel.id if channel else None)
        if channel is None:
            return await ctx.send("Birthdays will be announced in the channel where the command is used.")
        msg = f"Birthdays will be announced in {channel.mention}."
        if not channel.permissions_for(ctx.guild.me).send_messages:
            msg += "\n⚠️ I can't send messages there yet."
        await ctx.send(msg)

    @birthdayset.command(name="timezone")
    @commands.admin_or_permissions(manage_guild=True)
    @app_commands.describe(tz="IANA timezone, e.g. UTC or America/New_York")
    async def birthdayset_timezone(self, ctx: commands.Context, tz: str):
        """Set the timezone used to decide when midnight is."""
        try:
            ZoneInfo(tz)
        except (ZoneInfoNotFoundError, ValueError):
            return await ctx.send(
                f"`{tz}` isn't a valid IANA timezone. Try something like `America/New_York`.",
                allowed_mentions=NO_MENTIONS,
            )
        await self.config.guild(ctx.guild).timezone.set(tz)
        await ctx.send(f"Timezone set to `{tz}`. Birthday roles will come off at midnight there.")

    @birthdayset_timezone.autocomplete("tz")
    async def timezone_autocomplete(self, interaction: discord.Interaction, current: str):
        current = current.lower()
        return [app_commands.Choice(name=z, value=z) for z in TIMEZONES if current in z.lower()][:25]

    @birthdayset.command(name="allowrole")
    @commands.admin_or_permissions(manage_guild=True)
    @app_commands.describe(role="Role that may give birthday roles")
    async def birthdayset_allowrole(self, ctx: commands.Context, role: discord.Role):
        """Let a role use the birthday commands. Mods and members with Manage Roles always can."""
        async with self.config.guild(ctx.guild).allowed_roles() as allowed:
            if role.id not in allowed:
                allowed.append(role.id)
        await ctx.send(f"**{role.name}** can now give birthday roles.")

    @birthdayset.command(name="disallowrole")
    @commands.admin_or_permissions(manage_guild=True)
    @app_commands.describe(role="Role to stop from giving birthday roles")
    async def birthdayset_disallowrole(self, ctx: commands.Context, role: discord.Role):
        """Stop a role from using the birthday commands."""
        async with self.config.guild(ctx.guild).allowed_roles() as allowed:
            if role.id in allowed:
                allowed.remove(role.id)
        await ctx.send(f"**{role.name}** can no longer give birthday roles.")

    @birthdayset.command(name="message")
    @commands.admin_or_permissions(manage_guild=True)
    @app_commands.describe(message="Use {mention}, {name}, {server} and {cakes}. Leave empty for random messages.")
    async def birthdayset_message(self, ctx: commands.Context, *, message: Optional[str] = None):
        """Set a custom announcement. Placeholders: {mention} {name} {server} {cakes}.

        Leave empty to go back to the built-in random messages.
        """
        await self.config.guild(ctx.guild).message.set(message)
        if message is None:
            return await ctx.send("Back to the built-in random birthday messages.")
        await ctx.send("Custom birthday message saved. Preview:\n" + render(message, ctx.author), allowed_mentions=NO_MENTIONS)

    @birthdayset.command(name="test")
    @commands.admin_or_permissions(manage_guild=True)
    async def birthdayset_test(self, ctx: commands.Context):
        """Preview the birthday announcement here, without giving any role."""
        await ctx.defer(ephemeral=True)
        if not await self.announce(ctx.author, ctx.channel):
            await ctx.send("I couldn't send the preview here.", ephemeral=True)
        elif ctx.interaction:
            await ctx.send("Preview sent!", ephemeral=True)

    @birthdayset.command(name="settings")
    @commands.admin_or_permissions(manage_guild=True)
    async def birthdayset_settings(self, ctx: commands.Context):
        """Show the current Birthday settings."""
        data = await self.config.guild(ctx.guild).all()
        role = ctx.guild.get_role(data["birthday_role"] or 0)
        channel = ctx.guild.get_channel(data["birthday_channel"] or 0)
        allowed = [r.mention for r in map(ctx.guild.get_role, data["allowed_roles"]) if r]
        text = (
            f"**Birthday settings for {ctx.guild.name}**\n"
            f"**Role:** {role.mention if role else 'Not set'}\n"
            f"**Channel:** {channel.mention if channel else 'Where the command is used'}\n"
            f"**Timezone:** {data['timezone']}\n"
            f"**Allowed roles:** {humanize_list(allowed) if allowed else 'None'} (plus mods and Manage Roles)\n"
            f"**Message:** {data['message'] or 'Random built-in messages'}\n"
            f"**Celebrating now:** {len(data['scheduled_tasks'])}"
        )
        if role and (problem := self.role_problem(role)):
            text += f"\n⚠️ {problem}"
        for page in pagify(text):
            await ctx.send(page, ephemeral=True, allowed_mentions=NO_MENTIONS)
