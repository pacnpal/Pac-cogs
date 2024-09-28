import discord
from redbot.core import commands, checks
from redbot.core.bot import Red
from redbot.core.config import Config
from datetime import datetime, time, timedelta
import pytz

class Birthday(commands.Cog):
    """A cog to assign a birthday role until midnight Pacific Time."""

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890)
        default_guild = {
            "birthday_role": None,
            "allowed_roles": []
        }
        self.config.register_guild(**default_guild)
        self.birthday_tasks = {}

    @commands.group()
    @checks.admin_or_permissions(manage_roles=True)
    async def birthdayset(self, ctx):
        """Birthday cog settings."""
        pass

    @birthdayset.command()
    async def role(self, ctx, role: discord.Role):
        """Set the birthday role."""
        await self.config.guild(ctx.guild).birthday_role.set(role.id)
        await ctx.send(f"Birthday role set to {role.name}")

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
        """Assign the birthday role to a user until midnight Pacific Time."""
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

        await ctx.send(f"🎉 Happy Birthday, {member.mention}! You've been given the {birthday_role.name} role until midnight Pacific Time.")

        # Schedule role removal
        pacific_tz = pytz.timezone('US/Pacific')
        now = datetime.now(pacific_tz)
        midnight = pacific_tz.localize(datetime.combine(now.date() + timedelta(days=1), time.min))
        
        if ctx.guild.id in self.birthday_tasks:
            self.birthday_tasks[ctx.guild.id].cancel()
        
        self.birthday_tasks[ctx.guild.id] = self.bot.loop.create_task(self.remove_birthday_role(ctx.guild, member, birthday_role, midnight))

    async def remove_birthday_role(self, guild, member, role, when):
        """Remove the birthday role at the specified time."""
        await discord.utils.sleep_until(when)
        try:
            await member.remove_roles(role, reason="Birthday role duration expired")
        except (discord.Forbidden, discord.HTTPException):
            pass  # If we can't remove the role, we'll just let it be
        finally:
            del self.birthday_tasks[guild.id]

async def setup(bot):
    await bot.add_cog(Birthday(bot))
