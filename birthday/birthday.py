import discord # type: ignore
from redbot.core import commands, checks, app_commands # type: ignore
from redbot.core.bot import Red # type: ignore
from redbot.core.config import Config # type: ignore
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import logging
import asyncio
import secrets

# Set up logging
logger = logging.getLogger("red.birthday")

# Define context menu commands outside the class
@app_commands.context_menu(name="Give Birthday Role")
async def birthday_context_menu(interaction: discord.Interaction, member: discord.Member):
    try:
        # Defer the response immediately to prevent timeout
        await interaction.response.defer(ephemeral=True)
        
        cog = interaction.client.get_cog("Birthday")
        if not cog:
            logger.error("Birthday cog not loaded during context menu execution")
            await interaction.followup.send("Birthday cog is not loaded.", ephemeral=True)
            return

        # Check if the user has permission to use this command
        allowed_roles = await cog.config.guild(interaction.guild).allowed_roles()
        if not any(role.id in allowed_roles for role in interaction.user.roles):
            logger.warning(f"User {interaction.user.id} attempted to use birthday context menu without permission")
            return await interaction.followup.send("You don't have permission to use this command.", ephemeral=True)

        birthday_role_id = await cog.config.guild(interaction.guild).birthday_role()
        if not birthday_role_id:
            logger.error(f"Birthday role not set for guild {interaction.guild.id}")
            return await interaction.followup.send("The birthday role hasn't been set. An admin needs to set it using `/setrole`.", ephemeral=True)
        
        birthday_role = interaction.guild.get_role(birthday_role_id)
        if not birthday_role:
            logger.error("Birthday role not found in the guild")
            return await interaction.followup.send("The birthday role doesn't exist anymore. Please ask an admin to set it again.", ephemeral=True)

        # Assign the role, ignoring hierarchy
        try:
            await member.add_roles(birthday_role, reason="Birthday role")
            logger.info(f"Birthday role assigned to {member.id} in guild {interaction.guild.id}")
        except discord.Forbidden:
            logger.error("Failed to assign birthday role: Insufficient permissions")
            return await interaction.followup.send("I don't have permission to assign that role.", ephemeral=True)
        except discord.HTTPException as e:
            logger.error(f"Failed to assign birthday role: {str(e)}")
            return await interaction.followup.send("Failed to assign the birthday role due to a Discord error.", ephemeral=True)

        # Generate birthday message with random cakes (or pie)
        cakes = secrets.randbelow(6)
        if cakes == 0:
            message = f"🎉 Happy Birthday, {member.mention}! Sorry, out of cake today! Here's pie instead: 🥧"
        else:
            message = f"🎉 Happy Birthday, {member.mention}! Here's your cake{'s' if cakes > 1 else ''}: " + "🎂" * cakes

        # Get the birthday announcement channel
        birthday_channel_id = await cog.config.guild(interaction.guild).birthday_channel()
        if birthday_channel_id:
            channel = interaction.client.get_channel(birthday_channel_id)
            if not channel:
                logger.warning("Birthday channel not found in the guild")
                channel = interaction.channel
        else:
            channel = interaction.channel

        await channel.send(message)
        await interaction.followup.send("Birthday role assigned!", ephemeral=True)

        # Schedule role removal
        timezone = await cog.config.guild(interaction.guild).timezone()
        try:
            tz = ZoneInfo(timezone)
        except ZoneInfoNotFoundError:
            logger.warning("Invalid timezone for the guild, defaulting to UTC")
            await interaction.followup.send("Warning: Invalid timezone set. Defaulting to UTC.", ephemeral=True)
            tz = ZoneInfo("UTC")

        now = datetime.now(tz)
        midnight = datetime.combine(now.date() + timedelta(days=1), time.min).replace(tzinfo=tz)

        await cog.schedule_birthday_role_removal(interaction.guild, member, birthday_role, midnight)
    except Exception as e:
        logger.error(f"Unexpected error in birthday context menu: {str(e)}", exc_info=True)
        try:
            await interaction.followup.send(f"An error occurred: {str(e)}", ephemeral=True)
        except:
            pass

@app_commands.context_menu(name="Remove Birthday Role")
async def remove_birthday_context_menu(interaction: discord.Interaction, member: discord.Member):
    try:
        # Defer the response immediately to prevent timeout
        await interaction.response.defer(ephemeral=True)
        
        cog = interaction.client.get_cog("Birthday")
        if not cog:
            logger.error("Birthday cog not loaded during context menu execution")
            await interaction.followup.send("Birthday cog is not loaded.", ephemeral=True)
            return

        # Check if the user has permission to use this command
        allowed_roles = await cog.config.guild(interaction.guild).allowed_roles()
        if not any(role.id in allowed_roles for role in interaction.user.roles):
            logger.warning(f"User {interaction.user.id} attempted to remove birthday role without permission")
            return await interaction.followup.send("You don't have permission to use this command.", ephemeral=True)

        birthday_role_id = await cog.config.guild(interaction.guild).birthday_role()
        if not birthday_role_id:
            logger.error(f"Birthday role not set for guild {interaction.guild.id}")
            return await interaction.followup.send("The birthday role hasn't been set.", ephemeral=True)

        birthday_role = interaction.guild.get_role(birthday_role_id)
        if not birthday_role:
            logger.error("Birthday role not found in the guild")
            return await interaction.followup.send("The birthday role doesn't exist anymore.", ephemeral=True)

        if birthday_role not in member.roles:
            return await interaction.followup.send(f"{member.display_name} doesn't have the birthday role.", ephemeral=True)

        try:
            await member.remove_roles(birthday_role, reason="Birthday role manually removed")
            logger.info(f"Birthday role manually removed from {member.id} in guild {interaction.guild.id}")
        except discord.Forbidden:
            logger.error("Failed to remove birthday role: Insufficient permissions")
            return await interaction.followup.send("I don't have permission to remove that role.", ephemeral=True)
        except discord.HTTPException as e:
            logger.error(f"Failed to remove birthday role: {str(e)}")
            return await interaction.followup.send("Failed to remove the birthday role due to a Discord error.", ephemeral=True)

        # Remove scheduled task if it exists
        if str(member.id) in (await cog.config.guild(interaction.guild).scheduled_tasks()):
            await cog.config.guild(interaction.guild).scheduled_tasks.clear_raw(str(member.id))
            if interaction.guild.id in cog.birthday_tasks:
                cog.birthday_tasks[interaction.guild.id].cancel()
                del cog.birthday_tasks[interaction.guild.id]

        await interaction.followup.send(f"Birthday role removed from {member.display_name}!", ephemeral=True)
    except Exception as e:
        logger.error(f"Unexpected error in remove birthday context menu", exc_info=True)
        try:
            await interaction.followup.send(f"An error occurred: {str(e)}", ephemeral=True)
        except:
            pass

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
        self.cleanup_task = None
        self.bot.tree.add_command(birthday_context_menu)
        self.bot.tree.add_command(remove_birthday_context_menu)
        self.bot.loop.create_task(self.initialize())

    async def initialize(self):
        """Initialize the cog and start the cleanup task."""
        await self.bot.wait_until_ready()
        await self.reload_scheduled_tasks()
        self.cleanup_task = self.bot.loop.create_task(self.daily_cleanup())

    async def cog_unload(self):
        """Clean up tasks when the cog is unloaded."""
        if self.cleanup_task:
            self.cleanup_task.cancel()
        for task in self.birthday_tasks.values():
            task.cancel()
        self.bot.tree.remove_command(birthday_context_menu.name, type=discord.AppCommandType.user)
        self.bot.tree.remove_command(remove_birthday_context_menu.name, type=discord.AppCommandType.user)

    @commands.hybrid_command(name="removebirthday")
    @app_commands.guild_only()
    @app_commands.describe(member="The member to remove the birthday role from")
    async def remove_birthday(self, ctx: commands.Context, member: discord.Member):
        """Remove the birthday role from a user."""
        try:
            # Check if the user has permission to use this command
            allowed_roles = await self.config.guild(ctx.guild).allowed_roles()
            if not any(role.id in allowed_roles for role in ctx.author.roles):
                logger.warning(f"User {ctx.author.id} attempted to remove birthday role without permission")
                return await ctx.send("You don't have permission to use this command.", ephemeral=True)

            birthday_role_id = await self.config.guild(ctx.guild).birthday_role()
            if not birthday_role_id:
                logger.error(f"Birthday role not set for guild {ctx.guild.id}")
                return await ctx.send("The birthday role hasn't been set.", ephemeral=True)

            birthday_role = ctx.guild.get_role(birthday_role_id)
            if not birthday_role:
                logger.error(f"Birthday role {birthday_role_id} not found in guild {ctx.guild.id}")
                return await ctx.send("The birthday role doesn't exist anymore.", ephemeral=True)

            if birthday_role not in member.roles:
                return await ctx.send(f"{member.display_name} doesn't have the birthday role.", ephemeral=True)

            try:
                await member.remove_roles(birthday_role, reason="Birthday role manually removed")
                logger.info(f"Birthday role manually removed from {member.id} in guild {ctx.guild.id}")
            except discord.Forbidden:
                logger.error(f"Failed to remove birthday role from {member.id} in guild {ctx.guild.id}: Insufficient permissions")
                return await ctx.send("I don't have permission to remove that role.", ephemeral=True)
            except discord.HTTPException as e:
                logger.error(f"Failed to remove birthday role from {member.id} in guild {ctx.guild.id}: {str(e)}")
                return await ctx.send("Failed to remove the birthday role due to a Discord error.", ephemeral=True)

            # Remove scheduled task if it exists
            if str(member.id) in (await self.config.guild(ctx.guild).scheduled_tasks()):
                await self.config.guild(ctx.guild).scheduled_tasks.clear_raw(str(member.id))
                if ctx.guild.id in self.birthday_tasks:
                    self.birthday_tasks[ctx.guild.id].cancel()
                    del self.birthday_tasks[ctx.guild.id]

            await ctx.send(f"Birthday role removed from {member.display_name}!", ephemeral=True)
        except Exception as e:
            logger.error(f"Unexpected error in remove_birthday command: {str(e)}", exc_info=True)
            await ctx.send(f"An error occurred while removing the birthday role: {str(e)}", ephemeral=True)

    async def daily_cleanup(self):
        """Daily task to ensure all birthday roles are properly removed."""
        while True:
            try:
                await asyncio.sleep(3600)  # Check every hour
                logger.info("Running daily birthday role cleanup")
                
                for guild in self.bot.guilds:
                    try:
                        scheduled_tasks = await self.config.guild(guild).scheduled_tasks()
                        timezone = await self.config.guild(guild).timezone()
                        try:
                            tz = ZoneInfo(timezone)
                        except ZoneInfoNotFoundError:
                            logger.warning(f"Invalid timezone {timezone} for guild {guild.id}, defaulting to UTC")
                            tz = ZoneInfo("UTC")

                        now = datetime.now(tz)
                        
                        for member_id, task_info in scheduled_tasks.items():
                            try:
                                member = guild.get_member(int(member_id))
                                if not member:
                                    logger.warning(f"Member {member_id} not found in guild {guild.id}, removing task")
                                    await self.config.guild(guild).scheduled_tasks.clear_raw(member_id)
                                    continue

                                role = guild.get_role(task_info["role_id"])
                                if not role:
                                    logger.warning(f"Role {task_info['role_id']} not found in guild {guild.id}, removing task")
                                    await self.config.guild(guild).scheduled_tasks.clear_raw(member_id)
                                    continue

                                remove_at = datetime.fromisoformat(task_info["remove_at"]).replace(tzinfo=tz)
                                
                                if now >= remove_at:
                                    try:
                                        await member.remove_roles(role, reason="Birthday role duration expired (cleanup)")
                                        logger.info(f"Removed expired birthday role from {member_id} in guild {guild.id}")
                                    except discord.Forbidden:
                                        logger.error(f"Failed to remove birthday role from {member_id} in guild {guild.id}: Insufficient permissions")
                                    except discord.HTTPException as e:
                                        logger.error(f"Failed to remove birthday role from {member_id} in guild {guild.id}: {str(e)}")
                                    finally:
                                        await self.config.guild(guild).scheduled_tasks.clear_raw(member_id)
                            except Exception as e:
                                logger.error(f"Error processing task for member {member_id} in guild {guild.id}: {str(e)}", exc_info=True)
                    except Exception as e:
                        logger.error(f"Error processing guild {guild.id} in cleanup: {str(e)}", exc_info=True)
            except Exception as e:
                logger.error(f"Error in daily cleanup task: {str(e)}", exc_info=True)
            finally:
                await asyncio.sleep(3600)  # Wait an hour before next check

    @commands.hybrid_command(name="setrole")
    @app_commands.guild_only()
    @app_commands.describe(role="The role to set as the birthday role")
    @checks.is_owner()
    async def set_role(self, ctx: commands.Context, role: discord.Role):
        """Set the birthday role."""
        await self.config.guild(ctx.guild).birthday_role.set(role.id)
        await ctx.send(f"Birthday role set to {role.name}")

    @commands.hybrid_command(name="settimezone")
    @app_commands.guild_only()
    @app_commands.describe(tz="The timezone for role expiration (e.g., UTC, America/New_York)")
    @checks.is_owner()
    async def set_timezone(self, ctx: commands.Context, tz: str):
        """Set the timezone for the birthday role expiration."""
        try:
            ZoneInfo(tz)
            await self.config.guild(ctx.guild).timezone.set(tz)
            await ctx.send(f"Timezone set to {tz}")
        except ZoneInfoNotFoundError:
            await ctx.send(f"Invalid timezone: {tz}. Please use a valid IANA time zone identifier.")

    @commands.hybrid_command(name="setchannel")
    @app_commands.guild_only()
    @app_commands.describe(channel="The channel for birthday announcements")
    @checks.is_owner()
    async def set_channel(self, ctx: commands.Context, channel: discord.TextChannel):
        """Set the channel for birthday announcements."""
        await self.config.guild(ctx.guild).birthday_channel.set(channel.id)
        await ctx.send(f"Birthday announcement channel set to {channel.mention}")

    @commands.hybrid_command(name="birthdayallowrole")
    @app_commands.guild_only()
    @app_commands.describe(role="The role to allow using the birthday command")
    async def birthday_allow_role(self, ctx: commands.Context, role: discord.Role):
        """Add a role that can use the birthday command."""
        async with self.config.guild(ctx.guild).allowed_roles() as allowed_roles:
            if role.id not in allowed_roles:
                allowed_roles.append(role.id)
        await ctx.send(f"Added {role.name} to the list of roles that can use the birthday command.")

    @commands.hybrid_command(name="birthdayremoverole")
    @app_commands.guild_only()
    @app_commands.describe(role="The role to remove from using the birthday command")
    async def birthday_remove_role(self, ctx: commands.Context, role: discord.Role):
        """Remove a role from using the birthday command."""
        async with self.config.guild(ctx.guild).allowed_roles() as allowed_roles:
            if role.id in allowed_roles:
                allowed_roles.remove(role.id)
        await ctx.send(f"Removed {role.name} from the list of roles that can use the birthday command.")

    @commands.hybrid_command(name="birthday")
    @app_commands.guild_only()
    @app_commands.describe(member="The member to give the birthday role to")
    async def birthday(self, ctx: commands.Context, member: discord.Member):
        """Assign the birthday role to a user until midnight in the set timezone."""
        try:
            # Check if the user has permission to use this command
            allowed_roles = await self.config.guild(ctx.guild).allowed_roles()
            if not any(role.id in allowed_roles for role in ctx.author.roles):
                logger.warning(f"User {ctx.author.id} attempted to use birthday command without permission")
                return await ctx.send("You don't have permission to use this command.", ephemeral=True)

            birthday_role_id = await self.config.guild(ctx.guild).birthday_role()
            if not birthday_role_id:
                logger.error("Birthday role not set for the guild")
                return await ctx.send("The birthday role hasn't been set. An admin needs to set it using `/setrole`.", ephemeral=True)
            
            birthday_role = ctx.guild.get_role(birthday_role_id)
            if not birthday_role:
                logger.error("Birthday role not found in the guild")
                return await ctx.send("The birthday role doesn't exist anymore. Please ask an admin to set it again.", ephemeral=True)

            # Assign the role, ignoring hierarchy
            try:
                await member.add_roles(birthday_role, reason="Birthday role")
                logger.info(f"Birthday role assigned to {member.id} in guild {ctx.guild.id}")
            except discord.Forbidden:
                logger.error("Failed to assign birthday role: Insufficient permissions")
                return await ctx.send("I don't have permission to assign that role.", ephemeral=True)
            except discord.HTTPException as e:
                logger.error(f"Failed to assign birthday role: {str(e)}")
                return await ctx.send("Failed to assign the birthday role due to a Discord error.", ephemeral=True)

            # Generate birthday message with random cakes (or pie)
            cakes = secrets.SystemRandom().randint(0, 5)
            if cakes == 0:
                message = f"🎉 Happy Birthday, {member.mention}! Sorry, out of cake today! Here's pie instead: 🥧"
            else:
                message = f"🎉 Happy Birthday, {member.mention}! Here's your cake{'s' if cakes > 1 else ''}: " + "🎂" * cakes

            # Get the birthday announcement channel
            birthday_channel_id = await self.config.guild(ctx.guild).birthday_channel()
            if birthday_channel_id:
                channel = self.bot.get_channel(birthday_channel_id)
                if not channel:  # If the set channel doesn't exist anymore
                    logger.warning("Birthday channel not found in the guild")
                    channel = ctx.channel
            else:
                channel = ctx.channel

            await channel.send(message)
            await ctx.send("Birthday role assigned!", ephemeral=True)

            # Schedule role removal
            timezone = await self.config.guild(ctx.guild).timezone()
            try:
                tz = ZoneInfo(timezone)
            except ZoneInfoNotFoundError:
                logger.warning("Invalid timezone for the guild, defaulting to UTC")
                await ctx.send("Warning: Invalid timezone set. Defaulting to UTC.", ephemeral=True)
                tz = ZoneInfo("UTC")

            now = datetime.now(tz)
            midnight = datetime.combine(now.date() + timedelta(days=1), time.min).replace(tzinfo=tz)

            await self.schedule_birthday_role_removal(ctx.guild, member, birthday_role, midnight)
        except Exception as e:
            logger.error(f"Unexpected error in birthday command", exc_info=True)
            await ctx.send(f"An error occurred: {str(e)}", ephemeral=True)

    @commands.hybrid_command(name="bdaycheck")
    @app_commands.guild_only()
    async def bdaycheck(self, ctx: commands.Context):
        """Check the upcoming birthday role removal tasks."""
        try:
            # Check if the user has permission to use this command
            allowed_roles = await self.config.guild(ctx.guild).allowed_roles()
            if not any(role.id in allowed_roles for role in ctx.author.roles):
                logger.warning(f"User {ctx.author.id} attempted to use bdaycheck command without permission")
                return await ctx.send("You don't have permission to use this command.", ephemeral=True)

            scheduled_tasks = await self.config.guild(ctx.guild).scheduled_tasks()
            if not scheduled_tasks:
                return await ctx.send("There are no scheduled tasks.", ephemeral=True)

            message = "Upcoming birthday role removal tasks:\n"
            for member_id, task_info in scheduled_tasks.items():
                member = ctx.guild.get_member(int(member_id))
                if not member:
                    continue
                role = ctx.guild.get_role(task_info["role_id"])
                if not role:
                    continue
                remove_at = datetime.fromisoformat(task_info["remove_at"]).replace(tzinfo=ZoneInfo(await self.config.guild(ctx.guild).timezone()))
                message += f"- {member.display_name} ({member.id}): {role.name} will be removed at {remove_at}\n"

            await ctx.send(message, ephemeral=True)
        except Exception as e:
            logger.error(f"Unexpected error in bdaycheck command: {str(e)}", exc_info=True)
            await ctx.send(f"An error occurred while checking birthday tasks: {str(e)}", ephemeral=True)

    async def schedule_birthday_role_removal(self, guild, member, role, when):
        """Schedule the removal of the birthday role."""
        try:
            await self.config.guild(guild).scheduled_tasks.set_raw(str(member.id), value={
                "role_id": role.id,
                "remove_at": when.isoformat()
            })
            if guild.id in self.birthday_tasks:
                self.birthday_tasks[guild.id].cancel()
            self.birthday_tasks[guild.id] = self.bot.loop.create_task(self.remove_birthday_role(guild, member, role, when))
            logger.info(f"Scheduled birthday role removal for {member.id} in guild {guild.id} at {when}")
        except Exception as e:
            logger.error(f"Failed to schedule birthday role removal for {member.id} in guild {guild.id}: {str(e)}", exc_info=True)
            raise

    async def remove_birthday_role(self, guild, member, role, when):
        """Remove the birthday role at the specified time."""
        try:
            await discord.utils.sleep_until(when)
            try:
                await member.remove_roles(role, reason="Birthday role duration expired")
                logger.info(f"Birthday role removed from {member.id} in guild {guild.id}")
            except discord.Forbidden:
                logger.error(f"Failed to remove birthday role from {member.id} in guild {guild.id}: Insufficient permissions")
            except discord.HTTPException as e:
                logger.error(f"Failed to remove birthday role from {member.id} in guild {guild.id}: {str(e)}")
        except asyncio.CancelledError:
            logger.info(f"Birthday role removal task cancelled for {member.id} in guild {guild.id}")
            raise
        except Exception as e:
            logger.error(f"Error removing birthday role from {member.id} in guild {guild.id}: {str(e)}", exc_info=True)
        finally:
            if guild.id in self.birthday_tasks:
                del self.birthday_tasks[guild.id]
            await self.config.guild(guild).scheduled_tasks.clear_raw(str(member.id))

    async def reload_scheduled_tasks(self):
        """Reload and reschedule tasks from the configuration."""
        try:
            logger.info("Reloading scheduled birthday tasks")
            for guild in self.bot.guilds:
                try:
                    scheduled_tasks = await self.config.guild(guild).scheduled_tasks()
                    for member_id, task_info in scheduled_tasks.items():
                        try:
                            member = guild.get_member(int(member_id))
                            if not member:
                                logger.warning(f"Member {member_id} not found in guild {guild.id}, removing task")
                                await self.config.guild(guild).scheduled_tasks.clear_raw(member_id)
                                continue

                            role = guild.get_role(task_info["role_id"])
                            if not role:
                                logger.warning(f"Role {task_info['role_id']} not found in guild {guild.id}, removing task")
                                await self.config.guild(guild).scheduled_tasks.clear_raw(member_id)
                                continue

                            remove_at = datetime.fromisoformat(task_info["remove_at"]).replace(
                                tzinfo=ZoneInfo(await self.config.guild(guild).timezone()))
                            
                            if datetime.now(remove_at.tzinfo) >= remove_at:
                                try:
                                    await member.remove_roles(role, reason="Birthday role duration expired (reload)")
                                    logger.info(f"Removed expired birthday role from {member_id} in guild {guild.id}")
                                except discord.Forbidden:
                                    logger.error(f"Failed to remove birthday role from {member_id} in guild {guild.id}: Insufficient permissions")
                                except discord.HTTPException as e:
                                    logger.error(f"Failed to remove birthday role from {member_id} in guild {guild.id}: {str(e)}")
                                finally:
                                    await self.config.guild(guild).scheduled_tasks.clear_raw(member_id)
                            else:
                                self.birthday_tasks[guild.id] = self.bot.loop.create_task(
                                    self.remove_birthday_role(guild, member, role, remove_at))
                                logger.info(f"Rescheduled birthday role removal for {member_id} in guild {guild.id}")
                        except Exception as e:
                            logger.error(f"Error processing task for member {member_id} in guild {guild.id}: {str(e)}", exc_info=True)
                except Exception as e:
                    logger.error(f"Error processing guild {guild.id} during reload: {str(e)}", exc_info=True)
        except Exception as e:
            logger.error(f"Error reloading scheduled tasks: {str(e)}", exc_info=True)
