import aiohttp
from redbot.core import commands, Config, app_commands
from redbot.core.bot import Red
import asyncio
import json
import urllib.parse
import discord

class Overseerr(commands.Cog):
    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=3467367746)
        default_global = {
            "overseerr_url": None,
            "overseerr_api_key": None,
            "admin_role_name": "Overseerr Admin"
        }
        self.config.register_global(**default_global)

    @app_commands.command(name="seturl")
    @app_commands.guild_only()
    @app_commands.describe(url="The URL of your Overseerr instance")
    @commands.admin()
    async def set_url(self, interaction: discord.Interaction, url: str):
        """Set the Overseerr URL."""
        url = url.rstrip('/')
        await self.config.overseerr_url.set(url)
        await interaction.response.send_message(f"Overseerr URL set to: {url}")

    @app_commands.command(name="setapikey")
    @app_commands.guild_only()
    @app_commands.describe(api_key="Your Overseerr API key")
    @commands.admin()
    async def set_apikey(self, interaction: discord.Interaction, api_key: str):
        """Set the Overseerr API key."""
        await self.config.overseerr_api_key.set(api_key)
        await interaction.response.send_message("Overseerr API key has been set.")

    @app_commands.command(name="setadminrole")
    @app_commands.guild_only()
    @app_commands.describe(role_name="The name of the admin role")
    @commands.admin()
    async def set_adminrole(self, interaction: discord.Interaction, role_name: str):
        """Set the admin role name for Overseerr approvals."""
        await self.config.admin_role_name.set(role_name)
        await interaction.response.send_message(f"Admin role for Overseerr approvals set to: {role_name}")

    @app_commands.command(name="request")
    @app_commands.guild_only()
    @app_commands.describe(query="The name of the movie or TV show to search for")
    async def request(self, interaction: discord.Interaction, query: str):
        """Search and request a movie or TV show on Overseerr."""
        overseerr_url = await self.config.overseerr_url()
        overseerr_api_key = await self.config.overseerr_api_key()

        if not overseerr_url or not overseerr_api_key:
            await interaction.response.send_message("Overseerr is not configured. Please ask an admin to set it up using `/seturl` and `/setapikey`.", ephemeral=True)
            return

        search_url = f"{overseerr_url}/api/v1/search"
        headers = {
            "X-Api-Key": overseerr_api_key,
            "Content-Type": "application/json"
        }

        # Defer the response since this might take a while
        await interaction.response.defer()

        async with aiohttp.ClientSession() as session:
            async with session.get(search_url, headers=headers, params={"query": query}) as resp:
                if resp.status != 200:
                    await interaction.followup.send(f"Error from Overseerr API: {resp.status}", ephemeral=True)
                    return
                
                try:
                    search_results = await resp.json()
                except Exception as e:
                    await interaction.followup.send(f"Failed to parse JSON: {e}", ephemeral=True)
                    return

        if 'results' not in search_results:
            await interaction.followup.send(f"No results found for '{query}'. API Response: {search_results}", ephemeral=True)
            return

        if not search_results['results']:
            await interaction.followup.send(f"No results found for '{query}'.", ephemeral=True)
            return

        # Create select menu for results
        options = []
        for i, result in enumerate(search_results['results'][:25]):  # Discord limit is 25 options
            media_type = result['mediaType']
            title = result['title']
            release_date = result.get('releaseDate', 'N/A')
            status = await self.get_media_status(result['id'], media_type)
            
            # Truncate description if needed (Discord has a 100-character limit for option descriptions)
            description = f"[{media_type.upper()}] ({release_date}) - {status}"
            if len(description) > 100:
                description = description[:97] + "..."
                
            options.append(
                discord.SelectOption(
                    label=title[:100],  # Discord has a 100-character limit for labels
                    description=description,
                    value=str(i)
                )
            )

        select = discord.ui.Select(
            placeholder="Choose a title to request...",
            options=options,
            custom_id="media_select"
        )

        async def select_callback(select_interaction: discord.Interaction):
            selected_index = int(select_interaction.data['values'][0])
            selected_result = search_results['results'][selected_index]
            media_type = selected_result['mediaType']

            # Check if the media is already available or requested
            status = await self.get_media_status(selected_result['id'], media_type)
            if "Available" in status:
                await select_interaction.response.send_message(
                    f"'{selected_result['title']}' is already available. No need to request!",
                    ephemeral=True
                )
                return
            elif "Requested" in status:
                await select_interaction.response.send_message(
                    f"'{selected_result['title']}' has already been requested. No need to request again!",
                    ephemeral=True
                )
                return

            # Make the request
            request_url = f"{overseerr_url}/api/v1/request"
            request_data = {
                "mediaId": selected_result['id'],
                "mediaType": media_type
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(request_url, headers=headers, json=request_data) as resp:
                    if resp.status == 200:
                        response_data = await resp.json()
                        request_id = response_data.get('id')
                        await select_interaction.response.send_message(
                            f"Successfully requested {media_type} '{selected_result['title']}'! Request ID: {request_id}"
                        )
                    else:
                        await select_interaction.response.send_message(
                            f"Failed to request {media_type} '{selected_result['title']}'. Please try again later.",
                            ephemeral=True
                        )

        select.callback = select_callback
        view = discord.ui.View()
        view.add_item(select)
        await interaction.followup.send("Search results:", view=view)

    @app_commands.command(name="approve")
    @app_commands.guild_only()
    @app_commands.describe(request_id="The ID of the request to approve")
    async def approve(self, interaction: discord.Interaction, request_id: int):
        """Approve a request on Overseerr."""
        admin_role_name = await self.config.admin_role_name()
        if not any(role.name == admin_role_name for role in interaction.user.roles):
            await interaction.response.send_message(f"You need the '{admin_role_name}' role to approve requests.", ephemeral=True)
            return

        overseerr_url = await self.config.overseerr_url()
        overseerr_api_key = await self.config.overseerr_api_key()
        
        if not overseerr_url or not overseerr_api_key:
            await interaction.response.send_message("Overseerr is not configured. Please ask an admin to set it up using `/seturl` and `/setapikey`.", ephemeral=True)
            return

        approve_url = f"{overseerr_url}/api/v1/request/{request_id}/approve"
        headers = {
            "X-Api-Key": overseerr_api_key,
            "Content-Type": "application/json"
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(approve_url, headers=headers) as resp:
                if resp.status == 200:
                    await interaction.response.send_message(f"Request {request_id} has been approved!")
                else:
                    await interaction.response.send_message(f"Failed to approve request {request_id}. Please check the request ID and try again.", ephemeral=True)

    async def get_media_status(self, media_id, media_type):
        overseerr_url = await self.config.overseerr_url()
        overseerr_api_key = await self.config.overseerr_api_key()
        url = f"{overseerr_url}/api/v1/{'movie' if media_type == 'movie' else 'tv'}/{media_id}"
        headers = {"X-Api-Key": overseerr_api_key}
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    status = "Available" if data.get('mediaInfo', {}).get('status') == 3 else "Not Available"
                    if data.get('request'):
                        status += " (Requested)"
                    return status
                return "Status Unknown"
