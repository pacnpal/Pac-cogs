"""Look up parks, rides, companies and live wait times from the ThrillWiki public API."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import aiohttp
import discord  # type: ignore
from redbot.core import app_commands, commands  # type: ignore
from redbot.core.bot import Red  # type: ignore

log = logging.getLogger("red.pac-cogs.thrillwiki")

API = "https://www.thrillwiki.com/api/v1"
COLOR = discord.Color.from_rgb(37, 99, 235)


class NotFound(Exception):
    pass


def clip(text: str | None, limit: int = 350) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def metres(value: float | None) -> str | None:
    return None if value is None else f"{value:g} m ({value * 3.28084:.0f} ft)"


def kmh(value: float | None) -> str | None:
    return None if value is None else f"{value:g} km/h ({value * 0.621371:.0f} mph)"


def clock(iso: str) -> str:
    # The API sends park-local times with an offset, so formatting as-is shows park time.
    return f"{datetime.fromisoformat(iso):%I:%M %p}".lstrip("0")


def place(location: dict | None) -> str | None:
    if not location:
        return None
    return ", ".join(p for p in (location.get("city"), location.get("state"), location.get("country")) if p) or None


def add_fields(embed: discord.Embed, fields: dict[str, Any]) -> discord.Embed:
    # None and "" are absent; 0 is a real value (0 inversions, 0 coasters).
    for name, value in fields.items():
        if value is not None and value != "":
            embed.add_field(name=name, value=str(value), inline=True)
    return embed


def others(results: list[dict], label=lambda r: r["name"]) -> str | None:
    rest = [label(r) for r in results[1:6]]
    return "Also matched: " + ", ".join(rest) if rest else None


class ThrillWiki(commands.Cog):
    """Theme park and roller coaster lookups from ThrillWiki."""

    def __init__(self, bot: Red) -> None:
        self.bot = bot
        self.session = aiohttp.ClientSession(
            headers={"User-Agent": "Pac-cogs ThrillWiki (Red-DiscordBot)", "Accept": "application/json"},
            timeout=aiohttp.ClientTimeout(total=15),
        )

    async def cog_unload(self) -> None:
        await self.session.close()

    async def red_delete_data_for_user(self, **kwargs: Any) -> None:
        return  # Stores nothing about users.

    async def get(self, path: str, **params: Any) -> Any:
        async with self.session.get(f"{API}{path}", params=params) as resp:
            if resp.status == 404:
                raise NotFound
            resp.raise_for_status()
            return await resp.json()

    async def search(self, path: str, query: str) -> list[dict]:
        data = await self.get(path, search=query, page_size=6)
        if not data["results"]:
            raise NotFound
        return data["results"]

    async def cog_command_error(self, ctx: commands.Context, error: Exception) -> None:
        error = getattr(error, "original", error)
        if isinstance(error, NotFound):
            await ctx.send("Nothing on ThrillWiki matched that.")
        elif isinstance(error, (aiohttp.ClientError, TimeoutError)):
            log.warning("ThrillWiki API request failed: %s", error)
            await ctx.send("ThrillWiki didn't answer. Try again in a minute.")
        else:
            await self.bot.on_command_error(ctx, error, unhandled_by_cog=True)

    @commands.hybrid_group(name="thrillwiki", aliases=["tw"])
    async def thrillwiki(self, ctx: commands.Context) -> None:
        """Look things up on ThrillWiki."""

    @thrillwiki.command(name="park")
    @app_commands.describe(query="Park name to search for")
    async def park(self, ctx: commands.Context, *, query: str) -> None:
        """Show a park."""
        async with ctx.typing():
            results = await self.search("/parks/", query)
            p = results[0]
            embed = discord.Embed(title=p["name"], url=p["url"], description=clip(p.get("description")), color=COLOR)
            add_fields(embed, {
                "Location": place(p.get("location")) or ("Traveling" if not p.get("has_permanent_location") else None),
                "Status": p.get("display_status_display") or p.get("status_display"),
                "Operator": (p.get("operator") or {}).get("name"),
                "Rides": p.get("ride_count"),
                "Coasters": p.get("coaster_count"),
                "Rating": p.get("average_rating"),
            })
            if p.get("card_image_url"):
                embed.set_image(url=p["card_image_url"])
            if footer := others(results):
                embed.set_footer(text=footer)
        await ctx.send(embed=embed)

    @thrillwiki.command(name="ride", aliases=["attraction", "coaster"])
    @app_commands.describe(query="Ride or attraction name to search for")
    async def ride(self, ctx: commands.Context, *, query: str) -> None:
        """Show a ride, show or other attraction."""
        async with ctx.typing():
            results = await self.search("/attractions/", query)
            a = await self.get(f"/attractions/{results[0]['id']}/")
            park = a.get("park") or {}
            embed = discord.Embed(
                title=f"{a['display_name']} ({park['name']})" if park else a["display_name"],
                url=a["url"],
                description=clip(a.get("description")),
                color=COLOR,
            )
            add_fields(embed, {
                "Type": a.get("category_display") or a.get("attraction_type_display"),
                "Status": a.get("display_status_display") or a.get("status_display"),
                "Opened": a.get("opening_date"),
                "Closed": a.get("closing_date"),
                "Manufacturer": (a.get("manufacturer") or {}).get("name"),
                "Model": (a.get("ride_model") or {}).get("name"),
                "Height": metres(a.get("height_meters")),
                "Drop": metres(a.get("drop_meters")),
                "Length": metres(a.get("length_meters")),
                "Speed": kmh(a.get("max_speed_kmh")),
                "Inversions": a.get("inversions_count"),
                "Rating": a.get("average_rating"),
            })
            if a.get("banner_image_url"):
                embed.set_image(url=a["banner_image_url"])
            footer = others(results, lambda r: f"{r['display_name']} ({(r.get('park') or {}).get('name', '?')})")
            if footer:
                embed.set_footer(text=footer)
        await ctx.send(embed=embed)

    @thrillwiki.command(name="company", aliases=["manufacturer", "operator"])
    @app_commands.describe(query="Company name to search for")
    async def company(self, ctx: commands.Context, *, query: str) -> None:
        """Show a manufacturer, designer, operator or owner."""
        async with ctx.typing():
            results = await self.search("/companies/", query)
            c = results[0]
            embed = discord.Embed(
                title=c["name"],
                url=c["url"],
                description=clip(c.get("description")),
                color=COLOR,
            )
            add_fields(embed, {
                "Roles": ", ".join(c.get("roles_display") or []),
                "Founded": c.get("founded_year"),
                "Defunct": c.get("defunct_year"),
                "Parks": c.get("park_count") or None,
                "Rides": c.get("ride_count") or None,
                "Rating": c.get("average_rating"),
                "Website": c.get("website"),
            })
            if c.get("logo_url"):
                embed.set_thumbnail(url=c["logo_url"])
            if footer := others(results):
                embed.set_footer(text=footer)
        await ctx.send(embed=embed)

    @thrillwiki.command(name="waits", aliases=["live"])
    @app_commands.describe(query="Park name to search for")
    async def waits(self, ctx: commands.Context, *, query: str) -> None:
        """Show live wait times and today's hours for a park."""
        async with ctx.typing():
            p = (await self.search("/parks/", query))[0]
            live = await self.get(f"/parks/{p['slug']}/live/")
            if not live.get("supported"):
                await ctx.send(f"ThrillWiki has no live data for **{p['name']}**.")
                return
            hours = [
                f"{h['schedule_type_display']}: {clock(h['opening_time'])} to {clock(h['closing_time'])}"
                for h in (live.get("park") or {}).get("hours_today") or []
                if h.get("opening_time") and h.get("closing_time")
            ]
            rides = sorted(
                (a for a in live.get("attractions") or [] if a.get("wait_minutes") is not None),
                key=lambda a: a["wait_minutes"],
                reverse=True,
            )
            lines = [f"`{a['wait_minutes']:>3} min` {a['display_name']}" for a in rides[:20]]
            down = sum(1 for a in live.get("attractions") or [] if a.get("status") == "down")
            embed = discord.Embed(
                title=f"{p['name']}: live waits",
                url=p["url"],
                description="\n".join(hours + [""] + lines) if lines else "\n".join(hours + ["", "No posted waits right now."]),
                color=COLOR,
            )
            if down:
                embed.add_field(name="Down", value=str(down))
            attribution = live.get("attribution") or {}
            embed.set_footer(text=f"Live data from {attribution.get('name', 'ThemeParks.wiki')} via ThrillWiki")
        await ctx.send(embed=embed)

    @thrillwiki.command(name="stats")
    async def stats(self, ctx: commands.Context) -> None:
        """Show site-wide ThrillWiki counts."""
        async with ctx.typing():
            s = await self.get("/stats/")
            embed = discord.Embed(title="ThrillWiki stats", url="https://www.thrillwiki.com/", color=COLOR)
            add_fields(embed, {
                "Parks": f"{s['total_parks']:,} ({s['operating_parks']:,} operating)",
                "Attractions": f"{s['total_attractions']:,}",
                "Roller coasters": f"{s['total_roller_coasters']:,}",
                "Manufacturers": f"{s['total_manufacturers']:,}",
                "Photos": f"{s['total_photos']:,}",
                "Reviews": f"{s['total_reviews']:,}",
            })
            embed.set_footer(text=f"Updated {s.get('relative_last_updated', '')}")
        await ctx.send(embed=embed)
