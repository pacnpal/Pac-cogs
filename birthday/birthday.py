import discord
from redbot.core import commands, checks
from redbot.core.bot import Red
from redbot.core.config import Config
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import random

class Birthday(commands.Cog):
    """A cog to assign a birthday role until midnight in a specified timezone."""

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890)
        default_guild = {
            "birthday_role": None,
            "allowed_roles": [],
            "timezone": "UTC",
            "birthday_channel": None,
            "scheduled_tasks": {}
        }
        self.config.register_guild(**default_guild)
        self.birthday_tasks = {}

    @commands.group()
    @checks.admin_or_permissions(manage_roles=True)
    async def birthdayset(self, ctx):
        """Birthday cog settings."""
        pass

    @birthdayset.command()
    @checks.is_owner()
    async def role(self, ctx, role: discord.Role):
        """Set the birthday role."""
        await self.config.guild(ctx.guild).birthday_role.set(role.id)
        await ctx.send(f"Birthday role set to {role.name}")

    @birthdayset.command()
    @checks.is_owner()
    async def timezone(self, ctx, tz: str):
        """Set the timezone for the birthday role expiration."""
        try:
            ZoneInfo(tz)
            await self.config.guild(ctx.guild).timezone.set(tz)
            await ctx.send(f"Timezone set to {tz}")
        except ZoneInfoNotFoundError:
            await ctx.send(f"Invalid timezone: {tz}. Please use a valid IANA time zone identifier.")

    @birthdayset.command()
    @checks.is_owner()
    async def channel(self, ctx, channel: discord.TextChannel):
        """Set the channel for birthday announcements."""
        await self.config.guild(ctx.guild).birthday_channel.set(channel.id)
        await ctx.send(f"Birthday announcement channel set to {channel.mention}")

    @birthdayset.command()
    async def addrole(self, ctx, role: discord.Role):
        """Add a role that can use the birthday command."""
        async with self.config.guild(ctx.guild).allowed_roles() as allowed_roles:
            if role.id not in allowed_roles:
                allowed_roles.append(role.id)
        await ctx.send(f"Added {role.name} to the list of roles that can use the birthday command.")

    @birthdayset.command()
    async def removerole(self, ctx, role: discord.Role):
        """Remove a role from using the birthday command."""
        async with self.config.guild(ctx.guild).allowed_roles() as allowed_roles:
            if role.id in allowed_roles:
                allowed_roles.remove(role.id)
        await ctx.send(f"Removed {role.name} from the list of roles that can use the birthday command.")

    @commands.command()
    async def birthday(self, ctx, member: discord.Member):
        """Assign the birthday role to a user until midnight in the set timezone."""
        # Check if the user has permission to use this command
        allowed_roles = await self.config.guild(ctx.guild).allowed_roles()
        if not any(role.id in allowed_roles for role in ctx.author.roles):
            return await ctx.send("You don't have permission to use this command.")

        birthday_role_id = await self.config.guild(ctx.guild).birthday_role()
        if not birthday_role_id:
            return await ctx.send("The birthday role hasn't been set. An admin needs to set it using `[p]birthdayset role`.")
        
        birthday_role = ctx.guild.get_role(birthday_role_id)
        if not birthday_role:
            return await ctx.send("The birthday role doesn't exist anymore. Please ask an admin to set it again.")

        # Assign the role, ignoring hierarchy
        try:
            await member.add_roles(birthday_role, reason="Birthday role")
        except discord.Forbidden:
            return await ctx.send("I don't have permission to assign that role.")

        # Generate birthday message with random cakes (or pie)
        cakes = random.randint(0, 5)
        if cakes == 0:
            message = f"🎉 Happy Birthday, {member.mention}! Sorry, out of cake today! Here's pie instead: 🥧"
        else:
            message = f"🎉 Happy Birthday, {member.mention}! Here's your cake{'s' if cakes > 1 else ''}: " + "🎂" * cakes

        # Get the birthday announcement channel
        birthday_channel_id = await self.config.guild(ctx.guild).birthday_channel()
        if birthday_channel_id:
            channel = self.bot.get_channel(birthday_channel_id)
            if not channel:  # If the set channel doesn't exist anymore
                channel = ctx.channel
        else:
            channel = ctx.channel

        await channel.send(message)

        # Schedule role removal
        timezone = await self.config.guild(ctx.guild).timezone()
        try:
            tz = ZoneInfo(timezone)
        except ZoneInfoNotFoundError:
            await ctx.send(f"Warning: Invalid timezone set. Defaulting to UTC.")
            tz = ZoneInfo("UTC")

        now = datetime.now(tz)
        midnight = datetime.combine(now.date() + timedelta(days=1), time.min).replace(tzinfo=tz)

        await self.schedule_birthday_role_removal(ctx.guild, member, birthday_role, midnight)

    async def schedule_birthday_role_removal(self, guild, member, role, when):
        """Schedule the removal of the birthday role."""
        await self.config.guild(guild).scheduled_tasks.set_raw(str(member.id), value={
            "role_id": role.id,
            "remove_at": when.isoformat()
        })
        self.birthday_tasks[guild.id] = self.bot.loop.create_task(self.remove_birthday_role(guild, member, role, when))

    async def remove_birthday_role(self, guild, member, role, when):
        """Remove the birthday role at the specified time."""
        await discord.utils.sleep_until(when)
        try:
            await member.remove_roles(role, reason="Birthday role duration expired")
        except (discord.Forbidden, discord.HTTPException):
            pass  # If we can't remove the role, we'll just let it be
        finally:
            del self.birthday_tasks[guild.id]
            await self.config.guild(guild).scheduled_tasks.clear_raw(str(member.id))

    async def reload_scheduled_tasks(self):
        """Reload and reschedule tasks from the configuration."""
        for guild in self.bot.guilds:
            scheduled_tasks = await self.config.guild(guild).scheduled_tasks()
            for member_id, task_info in scheduled_tasks.items():
                member = guild.get_member(int(member_id))
                if not member:
                    continue
                role = guild.get_role(task_info["role_id"])
                if not role:
                    continue
                remove_at = datetime.fromisoformat(task_info["remove_at"]).replace(tzinfo=ZoneInfo(await self.config.guild(guild).timezone()))
                self.birthday_tasks[guild.id] = self.bot.loop.create_task(self.remove_birthday_role(guild, member, role, remove_at))

async def setup(bot):
    cog = Birthday(bot)
    await bot.add_cog(cog)
    await cog.reload_scheduled_tasks()