from redbot.core import commands, Config
from redbot.core.bot import Red
import asyncio
import json

class Overseerr(commands.Cog):
    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=336473788746)
        default_global = {
            "overseerr_url": None,
            "overseerr_api_key": None,
            "admin_role_name": "Overseerr Admin"
        }
        self.config.register_global(**default_global)

    @commands.group()
    @commands.admin()
    async def overseerr(self, ctx: commands.Context):
        """Manage Overseerr settings."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @overseerr.command(name="seturl")
    async def overseerr_seturl(self, ctx: commands.Context, url: str):
        """Set the Overseerr URL."""
        await self.config.overseerr_url.set(url)
        await ctx.send("Overseerr URL has been set.")

    @overseerr.command(name="setapikey")
    async def overseerr_setapikey(self, ctx: commands.Context, api_key: str):
        """Set the Overseerr API key."""
        await self.config.overseerr_api_key.set(api_key)
        await ctx.send("Overseerr API key has been set.")

    @overseerr.command(name="setadminrole")
    async def overseerr_setadminrole(self, ctx: commands.Context, role_name: str):
        """Set the admin role name for Overseerr approvals."""
        await self.config.admin_role_name.set(role_name)
        await ctx.send(f"Admin role for Overseerr approvals set to {role_name}.")

    async def get_media_status(self, media_id, media_type):
        overseerr_url = await self.config.overseerr_url()
        overseerr_api_key = await self.config.overseerr_api_key()
        url = f"{overseerr_url}/api/v1/{'movie' if media_type == 'movie' else 'tv'}/{media_id}"
        headers = {"X-Api-key": overseerr_api_key}
        
        async with self.bot.session.get(url, headers=headers) as resp:
            if resp.status == 200:
                data = await resp.json()
                status = "Available" if data.get('mediaInfo', {}).get('status') == 3 else "Not Available"
                if data.get('request'):
                    status += " (Requested)"
                return status
            return "Status Unknown"

    @commands.command()
    async def request(self, ctx: commands.Context, *, query: str):
        """Search and request a movie or TV show on Overseerr."""
        overseerr_url = await self.config.overseerr_url()
        overseerr_api_key = await self.config.overseerr_api_key()
        
        if not overseerr_url or not overseerr_api_key:
            await ctx.send("Overseerr is not configured. Please ask an admin to set it up.")
            return

        search_url = f"{overseerr_url}/api/v1/search"
        request_url = f"{overseerr_url}/api/v1/request"

        headers = {
            "X-Api-Key": overseerr_api_key,
            "Content-Type": "application/json"
        }

        # Search for the movie or TV show
        async with self.bot.session.get(search_url, headers=headers, params={"query": query}) as resp:
            search_results = await resp.json()

        if not search_results['results']:
            await ctx.send(f"No results found for '{query}'.")
            return

        # Display search results with availability status
        result_message = "Please choose a result by reacting with the corresponding number:\n\n"
        for i, result in enumerate(search_results['results'][:5], start=1):
            media_type = result['mediaType']
            status = await self.get_media_status(result['id'], media_type)
            result_message += f"{i}. [{media_type.upper()}] {result['title']} ({result.get('releaseDate', 'N/A')}) - {status}\n"

        result_msg = await ctx.send(result_message)

        # Add reaction options
        reactions = ['1️⃣', '2️⃣', '3️⃣', '4️⃣', '5️⃣']
        for i in range(min(len(search_results['results']), 5)):
            await result_msg.add_reaction(reactions[i])

        def check(reaction, user):
            return user == ctx.author and str(reaction.emoji) in reactions

        try:
            reaction, user = await self.bot.wait_for('reaction_add', timeout=60.0, check=check)
        except asyncio.TimeoutError:
            await ctx.send("Search timed out. Please try again.")
            return

        selected_index = reactions.index(str(reaction.emoji))
        selected_result = search_results['results'][selected_index]
        media_type = selected_result['mediaType']

        # Check if the media is already available or requested
        status = await self.get_media_status(selected_result['id'], media_type)
        if "Available" in status:
            await ctx.send(f"'{selected_result['title']}' is already available. No need to request!")
            return
        elif "Requested" in status:
            await ctx.send(f"'{selected_result['title']}' has already been requested. No need to request again!")
            return

        # Make the request
        request_data = {
            "mediaId": selected_result['id'],
            "mediaType": media_type
        }

        async with self.bot.session.post(request_url, headers=headers, json=request_data) as resp:
            if resp.status == 200:
                response_data = await resp.json()
                request_id = response_data.get('id')
                await ctx.send(f"Successfully requested {media_type} '{selected_result['title']}'! Request ID: {request_id}")
            else:
                await ctx.send(f"Failed to request {media_type} '{selected_result['title']}'. Please try again later.")

    @commands.command()
    async def approve(self, ctx: commands.Context, request_id: int):
        """Approve a request on Overseerr."""
        admin_role_name = await self.config.admin_role_name()
        if not any(role.name == admin_role_name for role in ctx.author.roles):
            await ctx.send(f"You need the '{admin_role_name}' role to approve requests.")
            return

        overseerr_url = await self.config.overseerr_url()
        overseerr_api_key = await self.config.overseerr_api_key()
        
        if not overseerr_url or not overseerr_api_key:
            await ctx.send("Overseerr is not configured. Please ask an admin to set it up.")
            return

        approve_url = f"{overseerr_url}/api/v1/request/{request_id}/approve"

        headers = {
            "X-Api-Key": overseerr_api_key,
            "Content-Type": "application/json"
        }

        async with self.bot.session.post(approve_url, headers=headers) as resp:
            if resp.status == 200:
                await ctx.send(f"Request {request_id} has been approved!")
            else:
                await ctx.send(f"Failed to approve request {request_id}. Please check the request ID and try again.")

def setup(bot: Red):
    bot.add_cog(Overseerr(bot))
