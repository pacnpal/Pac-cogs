import discord
from redbot.core import commands, checks, app_commands
from redbot.core.bot import Red
from redbot.core.config import Config
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import random

class Birthday(commands.Cog):
    """A cog to assign a birthday role until midnight in a specified timezone."""

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=5458102289)
        default_guild = {
            "birthday_role": None,
            "allowed_roles": [],
            "timezone": "UTC",
            "birthday_channel": None,
            "scheduled_tasks": {}
        }
        self.config.register_guild(**default_guild)
        self.birthday_tasks = {}

    @app_commands.command(name="setrole")
    @app_commands.guild_only()
    @app_commands.describe(role="The role to set as the birthday role")
    @checks.is_owner()
    async def set_role(self, interaction: discord.Interaction, role: discord.Role):
        """Set the birthday role."""
        await self.config.guild(interaction.guild).birthday_role.set(role.id)
        await interaction.response.send_message(f"Birthday role set to {role.name}")

    @app_commands.command(name="settimezone")
    @app_commands.guild_only()
    @app_commands.describe(tz="The timezone for role expiration (e.g., UTC, America/New_York)")
    @checks.is_owner()
    async def set_timezone(self, interaction: discord.Interaction, tz: str):
        """Set the timezone for the birthday role expiration."""
        try:
            ZoneInfo(tz)
            await self.config.guild(interaction.guild).timezone.set(tz)
            await interaction.response.send_message(f"Timezone set to {tz}")
        except ZoneInfoNotFoundError:
            await interaction.response.send_message(f"Invalid timezone: {tz}. Please use a valid IANA time zone identifier.")

    @app_commands.command(name="setchannel")
    @app_commands.guild_only()
    @app_commands.describe(channel="The channel for birthday announcements")
    @checks.is_owner()
    async def set_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        """Set the channel for birthday announcements."""
        await self.config.guild(interaction.guild).birthday_channel.set(channel.id)
        await interaction.response.send_message(f"Birthday announcement channel set to {channel.mention}")

    @app_commands.command(name="addrole")
    @app_commands.guild_only()
    @app_commands.describe(role="The role to allow using the birthday command")
    async def add_allowed_role(self, interaction: discord.Interaction, role: discord.Role):
        """Add a role that can use the birthday command."""
        async with self.config.guild(interaction.guild).allowed_roles() as allowed_roles:
            if role.id not in allowed_roles:
                allowed_roles.append(role.id)
        await interaction.response.send_message(f"Added {role.name} to the list of roles that can use the birthday command.")

    @app_commands.command(name="removerole")
    @app_commands.guild_only()
    @app_commands.describe(role="The role to remove from using the birthday command")
    async def remove_allowed_role(self, interaction: discord.Interaction, role: discord.Role):
        """Remove a role from using the birthday command."""
        async with self.config.guild(interaction.guild).allowed_roles() as allowed_roles:
            if role.id in allowed_roles:
                allowed_roles.remove(role.id)
        await interaction.response.send_message(f"Removed {role.name} from the list of roles that can use the birthday command.")

    @app_commands.command(name="birthday")
    @app_commands.guild_only()
    @app_commands.describe(member="The member to give the birthday role to")
    async def birthday(self, interaction: discord.Interaction, member: discord.Member):
        """Assign the birthday role to a user until midnight in the set timezone."""
        # Check if the user has permission to use this command
        allowed_roles = await self.config.guild(interaction.guild).allowed_roles()
        if not any(role.id in allowed_roles for role in interaction.user.roles):
            return await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)

        birthday_role_id = await self.config.guild(interaction.guild).birthday_role()
        if not birthday_role_id:
            return await interaction.response.send_message("The birthday role hasn't been set. An admin needs to set it using `/setrole`.", ephemeral=True)
        
        birthday_role = interaction.guild.get_role(birthday_role_id)
        if not birthday_role:
            return await interaction.response.send_message("The birthday role doesn't exist anymore. Please ask an admin to set it again.", ephemeral=True)

        # Assign the role, ignoring hierarchy
        try:
            await member.add_roles(birthday_role, reason="Birthday role")
        except discord.Forbidden:
            return await interaction.response.send_message("I don't have permission to assign that role.", ephemeral=True)

        # Generate birthday message with random cakes (or pie)
        cakes = random.randint(0, 5)
        if cakes == 0:
            message = f"🎉 Happy Birthday, {member.mention}! Sorry, out of cake today! Here's pie instead: 🥧"
        else:
            message = f"🎉 Happy Birthday, {member.mention}! Here's your cake{'s' if cakes > 1 else ''}: " + "🎂" * cakes

        # Get the birthday announcement channel
        birthday_channel_id = await self.config.guild(interaction.guild).birthday_channel()
        if birthday_channel_id:
            channel = self.bot.get_channel(birthday_channel_id)
            if not channel:  # If the set channel doesn't exist anymore
                channel = interaction.channel
        else:
            channel = interaction.channel

        await channel.send(message)
        await interaction.response.send_message("Birthday role assigned!", ephemeral=True)

        # Schedule role removal
        timezone = await self.config.guild(interaction.guild).timezone()
        try:
            tz = ZoneInfo(timezone)
        except ZoneInfoNotFoundError:
            await interaction.followup.send("Warning: Invalid timezone set. Defaulting to UTC.", ephemeral=True)
            tz = ZoneInfo("UTC")

        now = datetime.now(tz)
        midnight = datetime.combine(now.date() + timedelta(days=1), time.min).replace(tzinfo=tz)

        await self.schedule_birthday_role_removal(interaction.guild, member, birthday_role, midnight)

    @app_commands.command(name="bdaycheck")
    @app_commands.guild_only()
    async def bdaycheck(self, interaction: discord.Interaction):
        """Check the upcoming birthday role removal tasks."""
        # Check if the user has permission to use this command
        allowed_roles = await self.config.guild(interaction.guild).allowed_roles()
        if not any(role.id in allowed_roles for role in interaction.user.roles):
            return await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)

        scheduled_tasks = await self.config.guild(interaction.guild).scheduled_tasks()
        if not scheduled_tasks:
            return await interaction.response.send_message("There are no scheduled tasks.", ephemeral=True)

        message = "Upcoming birthday role removal tasks:\n"
        for member_id, task_info in scheduled_tasks.items():
            member = interaction.guild.get_member(int(member_id))
            if not member:
                continue
            role = interaction.guild.get_role(task_info["role_id"])
            if not role:
                continue
            remove_at = datetime.fromisoformat(task_info["remove_at"]).replace(tzinfo=ZoneInfo(await self.config.guild(interaction.guild).timezone()))
            message += f"- {member.display_name} ({member.id}): {role.name} will be removed at {remove_at}\n"

        await interaction.response.send_message(message, ephemeral=True)

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
