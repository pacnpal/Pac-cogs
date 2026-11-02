import asyncio
import hashlib
import ipaddress
import logging
import os
import secrets
import time
from collections import OrderedDict
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, Tuple

import aiohttp
import discord  # type: ignore
from yarl import URL
from aiohttp.abc import AbstractResolver
from redbot.core import Config, app_commands, commands  # type: ignore
from redbot.core.bot import Red  # type: ignore
from redbot.core.utils.chat_formatting import pagify  # type: ignore

logger = logging.getLogger("red.provenance")

API_URL = "https://api.openai.com/v1/content_provenance_checks"
MAX_BYTES = 50 * 1024 * 1024  # API upload limit (50 MiB)
MAX_REDIRECTS = 3
MAX_RETRIES = 4
API_CONCURRENCY = 2
AUTO_DOWNLOADS = 4  # auto scan files held in memory at once; extras are skipped
AUTO_PER_GUILD = 2  # slots one guild can hold, so a flood can't starve other guilds
CACHE_SIZE = 1024
CACHE_TTL = 6 * 60 * 60
GUILD_RATE = 10  # API calls allowed per guild...
GUILD_PER = 60  # ...per this many seconds of auto scanning

# Formats from the Content Provenance guide's "Supported uploads" section.
EXT_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".mp3": "audio/mpeg",
    ".opus": "audio/ogg",
    ".ogg": "audio/ogg",
    ".aac": "audio/aac",
    ".flac": "audio/flac",
    ".wav": "audio/wav",
    ".pcm": "audio/pcm",
}
TYPE_ALIASES = {
    "image/jpg": "image/jpeg",
    "audio/mp3": "audio/mpeg",
    "audio/opus": "audio/ogg",
    "audio/x-aac": "audio/aac",
    "audio/x-flac": "audio/flac",
    "audio/x-wav": "audio/wav",
    "audio/wave": "audio/wav",
    "audio/vnd.wave": "audio/wav",
}
SUPPORTED_TYPES = set(EXT_TYPES.values())

NOT_FOUND_NOTE = (
    "No OpenAI signal was found. That doesn't prove a person made it. Metadata can be "
    "stripped, watermarks can degrade, and content from other AI companies isn't checked."
)
FOOTER = "Only checks for OpenAI provenance signals (C2PA and SynthID)."


class ProvenanceError(Exception):
    """A check failed. The message is safe to show the user."""


def upload_type(filename: str, content_type: Optional[str]) -> Optional[str]:
    """Return the media type to upload, or None if the file isn't a supported format."""
    ext = os.path.splitext(filename.lower())[1]
    by_ext = EXT_TYPES.get(ext)
    if ext and by_ext is None:
        return None
    declared = (content_type or "").split(";")[0].strip().lower()
    declared = TYPE_ALIASES.get(declared, declared)
    if declared and declared not in SUPPORTED_TYPES:
        return None
    return by_ext or declared or None


def is_public_ip(host: str) -> bool:
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


class PublicResolver(AbstractResolver):
    """Resolves hostnames and refuses any that point at a non-public address."""

    def __init__(self) -> None:
        self._resolver = aiohttp.ThreadedResolver()

    async def resolve(self, host: str, port: int = 0, family: int = 0) -> List[Dict[str, Any]]:
        infos = await self._resolver.resolve(host, port, family)
        for info in infos:
            if not is_public_ip(info["host"]):
                raise OSError(f"{host} resolves to a non-public address")
        return infos

    async def close(self) -> None:
        await self._resolver.close()


def find_result(results: List[dict], kind: str) -> Optional[dict]:
    return next((r for r in results if r.get("type") == kind), None)


def detected(results: List[dict], kind: str) -> bool:
    entry = find_result(results, kind)
    return bool(entry and entry.get("outcome") == "detected")


def format_time(value: str) -> str:
    try:
        return discord.utils.format_dt(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError:
        return value


def describe(entry: dict) -> str:
    kind = entry.get("type")
    found = entry.get("outcome") == "detected"
    if kind == "c2pa":
        lines = ["**OpenAI Content Credentials detected**" if found else "No OpenAI Content Credentials found"]
        state = entry.get("validation_state")
        if state and state != "not_present":
            lines.append(f"Manifest: {state}" + (" (not reliable evidence)" if state == "invalid" else ""))
        if entry.get("issuer"):
            lines.append(f"Issuer: {entry['issuer']}")
    else:
        lines = ["**OpenAI SynthID watermark detected**" if found else "No OpenAI SynthID watermark found"]
    if entry.get("model"):
        lines.append(f"Model: {entry['model']}")
    if entry.get("generated_at"):
        lines.append(f"Generated: {format_time(entry['generated_at'])}")
    return "\n".join(lines)


class Provenance(commands.Cog):
    """Check images and audio for OpenAI provenance signals (C2PA and SynthID)."""

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=7365821904)
        default_guild = {
            "auto_scan": False,
            "channel_mode": "allow",
            "channels": [],
            "c2pa_replies": False,
            "avatar_scan": False,
            "audio_scan": False,
            "log_channel": None,
        }
        self.config.register_guild(**default_guild)
        self.cache: "OrderedDict[str, Tuple[float, List[dict]]]" = OrderedDict()
        self.api_semaphore = asyncio.Semaphore(API_CONCURRENCY)
        self.auto_semaphore = asyncio.Semaphore(AUTO_DOWNLOADS)
        self.guild_slots: Dict[int, asyncio.Semaphore] = {}
        self.guild_cooldowns: Dict[int, commands.Cooldown] = {}
        self.paused = False  # set when the key has no Content Provenance access
        self.owner_notified = False
        self.session: Optional[aiohttp.ClientSession] = None
        self.fetch_session: Optional[aiohttp.ClientSession] = None

    async def cog_load(self) -> None:
        self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60))
        self.fetch_session = aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(resolver=PublicResolver()),
            timeout=aiohttp.ClientTimeout(total=30),
        )

    async def cog_unload(self) -> None:
        for session in (self.session, self.fetch_session):
            if session:
                await session.close()

    async def red_delete_data_for_user(self, *, requester, user_id: int) -> None:
        """Nothing to delete. This cog stores no user data."""
        return

    @commands.Cog.listener()
    async def on_red_api_tokens_update(self, service_name: str, api_tokens: Dict[str, str]) -> None:
        if service_name == "openai":
            self.paused = False
            self.owner_notified = False

    # ---- API ----

    async def check_bytes(self, data: bytes, filename: str, media_type: str, guild_id: Optional[int] = None) -> List[dict]:
        """Return the API's results list for this file. Raises ProvenanceError on failure.

        Pass guild_id for auto scans so the per-guild rate limit applies. Cache hits are free.
        """
        digest = hashlib.sha256(data).hexdigest()
        cached = self._cached(digest)
        if cached is not None:
            return cached

        api_key = (await self.bot.get_shared_api_tokens("openai")).get("api_key")
        if not api_key:
            raise ProvenanceError("No OpenAI API key is set. The bot owner can set one with `[p]set api openai api_key,<key>`.")
        if self.paused:
            raise ProvenanceError("The OpenAI API key doesn't have Content Provenance access.")

        async with self.api_semaphore:
            # An identical file may have finished while this call waited for the semaphore.
            cached = self._cached(digest)
            if cached is not None:
                return cached
            if guild_id is not None:
                bucket = self.guild_cooldowns.setdefault(guild_id, commands.Cooldown(GUILD_RATE, GUILD_PER))
                if bucket.update_rate_limit():
                    raise ProvenanceError("Auto scan rate limit reached for this server.")

            for attempt in range(MAX_RETRIES):
                form = aiohttp.FormData()
                form.add_field("file", data, filename=filename, content_type=media_type)
                try:
                    async with self.session.post(API_URL, data=form, headers={"Authorization": f"Bearer {api_key}"}) as resp:
                        if resp.status == 200:
                            results = (await resp.json()).get("results") or []
                            self.cache[digest] = (time.monotonic(), results)
                            if len(self.cache) > CACHE_SIZE:
                                self.cache.popitem(last=False)
                            return results
                        body = await resp.text()
                        retry_after = resp.headers.get("Retry-After")
                        status = resp.status
                except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                    logger.warning(f"Content Provenance request failed: {e!r}")
                    status, body, retry_after = 0, "", None

                if status == 400:
                    logger.info(f"Content Provenance API rejected {filename}: {body[:300]}")
                    raise ProvenanceError("OpenAI couldn't check that file. It may be malformed, unsupported, or too long.")
                if status in (401, 404):
                    await self._lost_access(status)
                    raise ProvenanceError("The OpenAI API key doesn't have Content Provenance access.")
                if status not in (0, 429) and status < 500:
                    logger.error(f"Content Provenance API returned {status}: {body[:300]}")
                    raise ProvenanceError("The OpenAI API returned an unexpected error.")

                if attempt + 1 < MAX_RETRIES:
                    try:
                        delay = float(retry_after) if retry_after else 2 ** attempt
                    except ValueError:
                        delay = 2 ** attempt
                    delay = min(delay, 30) + secrets.SystemRandom().uniform(0, 1)
                    logger.debug(f"Content Provenance API status {status}, retrying in {delay:.1f}s")
                    await asyncio.sleep(delay)

        logger.warning(f"Content Provenance API still failing after {MAX_RETRIES} attempts")
        raise ProvenanceError("The OpenAI API is busy or unavailable. Try again later.")

    def _cached(self, digest: str) -> Optional[List[dict]]:
        hit = self.cache.get(digest)
        if hit and time.monotonic() - hit[0] < CACHE_TTL:
            self.cache.move_to_end(digest)
            return hit[1]
        return None

    async def _lost_access(self, status: int) -> None:
        self.paused = True
        if self.owner_notified:
            return
        self.owner_notified = True
        logger.error(f"Content Provenance API returned {status}. Pausing auto scans until the openai token changes.")
        reason = "was rejected" if status == 401 else "doesn't have access to the Content Provenance API"
        try:
            await self.bot.send_to_owners(
                f"Provenance: the OpenAI API key {reason} (HTTP {status}). "
                "Automatic scans are paused until the `openai` API token is changed with `[p]set api openai api_key,<key>`."
            )
        except Exception as e:
            logger.error(f"Failed to notify owners: {e!r}")

    async def fetch_url(self, url: str) -> Tuple[bytes, str, Optional[str]]:
        """Download a URL with SSRF protection. Returns (data, filename, content_type)."""
        try:
            target = URL(url)
        except ValueError:
            raise ProvenanceError("That isn't a valid URL.") from None
        for _ in range(MAX_REDIRECTS + 1):
            # Check the host exactly as aiohttp will connect to it. yarl normalizes hosts
            # (fullwidth digits become ASCII), so checking the raw string misses some IPs.
            host = target.raw_host
            if target.scheme not in ("http", "https") or not host:
                raise ProvenanceError("Only http and https URLs can be checked.")
            try:
                ipaddress.ip_address(host)
                literal = True
            except ValueError:
                literal = False
            # Literal IPs skip the resolver in aiohttp, so check them here.
            # Hostnames are checked by PublicResolver after DNS resolution.
            if literal and not is_public_ip(host):
                raise ProvenanceError("That URL points at a private address.")
            try:
                async with self.fetch_session.get(target, allow_redirects=False) as resp:
                    if resp.status in (301, 302, 303, 307, 308) and "Location" in resp.headers:
                        try:
                            target = target.join(URL(resp.headers["Location"]))
                        except ValueError:
                            raise ProvenanceError("The URL redirected somewhere invalid.") from None
                        continue
                    if resp.status != 200:
                        raise ProvenanceError(f"The URL returned HTTP {resp.status}.")
                    if (resp.content_length or 0) > MAX_BYTES:
                        raise ProvenanceError("That file is over the 50 MiB limit.")
                    data = bytearray()
                    async for chunk in resp.content.iter_chunked(65536):
                        data.extend(chunk)
                        if len(data) > MAX_BYTES:
                            raise ProvenanceError("That file is over the 50 MiB limit.")
                    filename = os.path.basename(resp.url.path) or "file"
                    return bytes(data), filename, resp.headers.get("Content-Type")
            except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as e:
                logger.info(f"URL fetch failed for {target}: {e!r}")
                raise ProvenanceError("Couldn't download that URL.") from e
        raise ProvenanceError("Too many redirects.")

    # ---- Output ----

    def results_embed(self, title: str, results: List[dict], color: discord.Color) -> discord.Embed:
        embed = discord.Embed(title=title[:256], color=color)
        for kind, name in (("c2pa", "C2PA Content Credentials"), ("synthid", "SynthID watermark")):
            entry = find_result(results, kind)
            if entry:
                embed.add_field(name=name, value=describe(entry)[:1024], inline=False)
        if not any(r.get("outcome") == "detected" for r in results):
            embed.description = NOT_FOUND_NOTE
        embed.set_footer(text=FOOTER)
        return embed

    # ---- Manual check ----

    @commands.hybrid_command(name="provenance")
    @app_commands.guild_only()
    @app_commands.describe(file="An image or audio file to check", url="A link to an image or audio file")
    @commands.cooldown(1, 10, commands.BucketType.user)
    async def provenance(self, ctx: commands.Context, file: Optional[discord.Attachment] = None, *, url: Optional[str] = None):
        """Check an attachment, a replied-to message, or a URL for OpenAI provenance signals.

        This only detects OpenAI's C2PA Content Credentials and SynthID watermark.
        Finding nothing doesn't prove a person made the file.
        """
        # Prefix invocations consume the first attachment into `file`, so read them all from the message.
        attachments = ([file] if file else []) if ctx.interaction else list(ctx.message.attachments)
        if not attachments and not url:
            ref = ctx.message.reference
            if ref and ref.message_id:
                try:
                    replied = ref.resolved if isinstance(ref.resolved, discord.Message) else await ctx.channel.fetch_message(ref.message_id)
                    attachments = list(replied.attachments)
                except discord.HTTPException:
                    pass
        if not attachments and not url:
            return await ctx.send("Attach a file, reply to a message with attachments, or give a URL.", ephemeral=True)

        await ctx.defer()
        color = await ctx.embed_color()
        embeds: List[discord.Embed] = []
        errors: List[str] = []
        if url:
            url = url.strip("<>")
            try:
                data, filename, content_type = await self.fetch_url(url)
                media_type = upload_type(filename, content_type)
                if not media_type:
                    raise ProvenanceError("That isn't a supported image or audio format.")
                embeds.append(self.results_embed(filename, await self.check_bytes(data, filename, media_type), color))
            except ProvenanceError as e:
                errors.append(str(e).replace("[p]", ctx.clean_prefix))
        for attachment in attachments[:10]:
            name = attachment.filename
            media_type = upload_type(name, attachment.content_type)
            try:
                if not media_type:
                    raise ProvenanceError("not a supported image or audio format.")
                if attachment.size > MAX_BYTES:
                    raise ProvenanceError("over the 50 MiB limit.")
                data = await attachment.read()
                embeds.append(self.results_embed(name, await self.check_bytes(data, name, media_type), color))
            except ProvenanceError as e:
                errors.append(f"{discord.utils.escape_markdown(name)}: {e}".replace("[p]", ctx.clean_prefix))
            except discord.HTTPException:
                errors.append(f"{discord.utils.escape_markdown(name)}: couldn't download it from Discord.")

        # Discord allows 10 embeds and 6000 embed characters per message, so send in batches.
        batch: List[discord.Embed] = []
        for embed in embeds:
            if len(batch) == 10 or sum(map(len, batch)) + len(embed) > 6000:
                await ctx.send(embeds=batch)
                batch = []
            batch.append(embed)
        await ctx.send(content="\n".join(errors)[:2000] or None, embeds=batch)

    # ---- Auto scan ----

    def auto_slot(self, key: int) -> Optional[asyncio.Semaphore]:
        """Return the per-guild slot if automatic work for this key can start now, else None.

        Automatic scans skip instead of queueing, so a flood can't pile up downloads. Each key
        gets at most AUTO_PER_GUILD of the AUTO_DOWNLOADS global slots, and a guild that's out
        of rate-limit tokens is skipped before anything is downloaded.
        """
        slot = self.guild_slots.setdefault(key, asyncio.Semaphore(AUTO_PER_GUILD))
        bucket = self.guild_cooldowns.get(key)
        if self.auto_semaphore.locked() or slot.locked() or (bucket and bucket.get_tokens() == 0):
            return None
        return slot

    async def scanning_ready(self, guild: Optional[discord.Guild]) -> bool:
        if guild is None or self.paused or await self.bot.cog_disabled_in_guild(self, guild):
            return False
        return bool((await self.bot.get_shared_api_tokens("openai")).get("api_key"))

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or not message.attachments or not await self.scanning_ready(message.guild):
            return
        settings = await self.config.guild(message.guild).all()
        if not settings["auto_scan"]:
            return
        channel_ids = {message.channel.id, getattr(message.channel, "parent_id", None)}
        listed = bool(channel_ids & set(settings["channels"]))
        if listed != (settings["channel_mode"] == "allow"):
            return

        lines = []
        for attachment in message.attachments:
            media_type = upload_type(attachment.filename, attachment.content_type)
            if not media_type or attachment.size > MAX_BYTES:
                continue
            if media_type.startswith("audio/") and not settings["audio_scan"]:
                continue
            guild_slot = self.auto_slot(message.guild.id)
            if guild_slot is None:
                logger.debug(f"Auto scan busy or rate limited, skipped {attachment.filename} in guild {message.guild.id}")
                continue
            try:
                async with self.auto_semaphore, guild_slot:
                    # No local name for the bytes, so they're freed when check_bytes returns
                    # instead of living on while the reply below is sent.
                    results = await self.check_bytes(await attachment.read(), attachment.filename, media_type, guild_id=message.guild.id)
            except (ProvenanceError, discord.HTTPException) as e:
                logger.debug(f"Auto scan skipped {attachment.filename} in guild {message.guild.id}: {e}")
                continue
            name = discord.utils.escape_markdown(attachment.filename)
            synthid = detected(results, "synthid")
            if synthid:
                lines.append(f"OpenAI SynthID watermark detected in {name}.")
            if detected(results, "c2pa") and (synthid or settings["c2pa_replies"]):
                lines.append(f"OpenAI Content Credentials detected in {name}.")

        if lines:
            lines.append(f"-# {FOOTER}")
            try:
                # Long filenames can push the reply past Discord's 2000 character limit.
                for page in pagify("\n".join(lines)):
                    await message.reply(page, mention_author=False)
            except discord.HTTPException as e:
                logger.info(f"Couldn't reply in channel {message.channel.id}: {e}")

    # ---- Avatar scan ----

    async def scan_avatar(self, asset: discord.Asset, guild_id: Optional[int] = None) -> Optional[List[dict]]:
        """Scan an avatar asset. Returns results when something was detected, otherwise None."""
        asset = asset.with_size(4096)
        filename = "avatar.gif" if asset.is_animated() else "avatar.png"
        # Global avatar changes have no guild, so they share slot key 0 (no guild has ID 0).
        slot = self.auto_slot(guild_id or 0)
        if slot is None:
            logger.debug(f"Avatar scan busy or rate limited, skipped for guild {guild_id}")
            return None
        try:
            async with self.auto_semaphore, slot:
                data = await asset.read()
                if len(data) > MAX_BYTES:
                    return None
                results = await self.check_bytes(data, filename, EXT_TYPES[filename[-4:]], guild_id=guild_id)
        except (ProvenanceError, discord.HTTPException) as e:
            logger.debug(f"Avatar scan skipped: {e}")
            return None
        return results if any(r.get("outcome") == "detected" for r in results) else None

    async def avatar_log_channel(self, guild: discord.Guild) -> Optional[discord.abc.Messageable]:
        if not await self.scanning_ready(guild):
            return None
        settings = await self.config.guild(guild).all()
        if not settings["avatar_scan"] or not settings["log_channel"]:
            return None
        return guild.get_channel(settings["log_channel"])

    async def post_avatar_log(self, channel: discord.abc.Messageable, user: discord.abc.User, asset: discord.Asset, results: List[dict], kind: str) -> None:
        embed = self.results_embed(f"OpenAI provenance signal on {kind}", results, discord.Color.orange())
        embed.description = f"{user.mention} (`{user.id}`)"
        embed.set_thumbnail(url=asset.url)
        try:
            await channel.send(embed=embed)
        except discord.HTTPException as e:
            logger.info(f"Couldn't post avatar log: {e}")

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        asset = member.guild_avatar or member.avatar
        if member.bot or asset is None:
            return
        channel = await self.avatar_log_channel(member.guild)
        if channel is None:
            return
        results = await self.scan_avatar(asset, guild_id=member.guild.id)
        if results:
            await self.post_avatar_log(channel, member, asset, results, "avatar (member joined)")

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        if after.bot or before.guild_avatar == after.guild_avatar or after.guild_avatar is None:
            return
        channel = await self.avatar_log_channel(after.guild)
        if channel is None:
            return
        results = await self.scan_avatar(after.guild_avatar, guild_id=after.guild.id)
        if results:
            await self.post_avatar_log(channel, after, after.guild_avatar, results, "server avatar")

    @commands.Cog.listener()
    async def on_user_update(self, before: discord.User, after: discord.User) -> None:
        if after.bot or before.avatar == after.avatar or after.avatar is None:
            return
        channels = []
        for guild in after.mutual_guilds:
            channel = await self.avatar_log_channel(guild)
            if channel is not None:
                channels.append(channel)
        if not channels:
            return
        results = await self.scan_avatar(after.avatar)  # scanned once for every guild
        if results:
            for channel in channels:
                await self.post_avatar_log(channel, after, after.avatar, results, "global avatar")

    # ---- Settings ----

    @commands.hybrid_group(name="provenanceset", fallback="show")
    @app_commands.guild_only()
    @commands.guild_only()
    @commands.admin_or_permissions(administrator=True)
    async def provenanceset(self, ctx: commands.Context):
        """Show the Provenance settings for this server."""
        if ctx.invoked_subcommand is not None:
            return
        settings = await self.config.guild(ctx.guild).all()
        channels = ", ".join(f"<#{c}>" for c in settings["channels"]) or "None"
        mode = "Allowlist (only these)" if settings["channel_mode"] == "allow" else "Denylist (all except these)"
        has_key = bool((await self.bot.get_shared_api_tokens("openai")).get("api_key"))
        embed = discord.Embed(title="Provenance settings", color=await ctx.embed_color())
        embed.add_field(name="Auto scan", value="On" if settings["auto_scan"] else "Off")
        embed.add_field(name="C2PA-only replies", value="On" if settings["c2pa_replies"] else "Off")
        embed.add_field(name="Audio scan", value="On" if settings["audio_scan"] else "Off")
        embed.add_field(name="Avatar scan", value="On" if settings["avatar_scan"] else "Off")
        embed.add_field(name="Log channel", value=f"<#{settings['log_channel']}>" if settings["log_channel"] else "Not set")
        embed.add_field(name="API key", value=("Paused (no access)" if self.paused else "Set") if has_key else "Not set")
        embed.add_field(name="Channel mode", value=mode, inline=False)
        embed.add_field(name="Channels", value=channels[:1024], inline=False)
        embed.set_footer(text=FOOTER)
        await ctx.send(embed=embed)

    async def _toggle(self, ctx: commands.Context, key: str, label: str, enabled: bool) -> None:
        await self.config.guild(ctx.guild).set_raw(key, value=enabled)
        await ctx.send(f"{label} {'enabled' if enabled else 'disabled'}.")

    @provenanceset.command(name="autoscan")
    @commands.admin_or_permissions(administrator=True)
    @app_commands.describe(enabled="Scan image attachments in the configured channels")
    async def set_autoscan(self, ctx: commands.Context, enabled: bool):
        """Turn automatic attachment scanning on or off."""
        await self._toggle(ctx, "auto_scan", "Auto scan", enabled)

    @provenanceset.command(name="c2pareplies")
    @commands.admin_or_permissions(administrator=True)
    @app_commands.describe(enabled="Reply when only Content Credentials are detected")
    async def set_c2pareplies(self, ctx: commands.Context, enabled: bool):
        """Reply to auto scan detections that only have C2PA Content Credentials.

        SynthID detections always get a reply. This covers images with OpenAI Content Credentials but no watermark.
        """
        await self._toggle(ctx, "c2pa_replies", "C2PA-only replies", enabled)

    @provenanceset.command(name="audioscan")
    @commands.admin_or_permissions(administrator=True)
    @app_commands.describe(enabled="Also scan audio attachments during auto scan")
    async def set_audioscan(self, ctx: commands.Context, enabled: bool):
        """Include audio attachments in auto scan (SynthID only)."""
        await self._toggle(ctx, "audio_scan", "Audio scan", enabled)

    @provenanceset.command(name="avatarscan")
    @commands.admin_or_permissions(administrator=True)
    @app_commands.describe(enabled="Scan member avatars and post detections to the log channel")
    async def set_avatarscan(self, ctx: commands.Context, enabled: bool):
        """Scan avatars on join and on change. Needs a log channel and the members intent."""
        await self._toggle(ctx, "avatar_scan", "Avatar scan", enabled)
        if enabled and not await self.config.guild(ctx.guild).log_channel():
            await ctx.send("Set a log channel with `provenanceset setlog` or nothing will be posted.")

    @provenanceset.command(name="setlog")
    @commands.admin_or_permissions(administrator=True)
    @app_commands.describe(channel="Where avatar detections are posted. Leave empty to clear.")
    async def set_log(self, ctx: commands.Context, channel: Optional[discord.TextChannel] = None):
        """Set the private channel for avatar scan results."""
        await self.config.guild(ctx.guild).log_channel.set(channel.id if channel else None)
        await ctx.send(f"Log channel set to {channel.mention}." if channel else "Log channel cleared.")

    @provenanceset.command(name="channelmode")
    @commands.admin_or_permissions(administrator=True)
    @app_commands.describe(mode="allow: only scan listed channels. deny: scan everything except listed channels.")
    async def set_channelmode(self, ctx: commands.Context, mode: Literal["allow", "deny"]):
        """Choose whether the channel list is an allowlist or a denylist."""
        await self.config.guild(ctx.guild).channel_mode.set(mode)
        await ctx.send(f"Channel mode set to {mode}list.")

    @provenanceset.command(name="addchannel")
    @commands.admin_or_permissions(administrator=True)
    @app_commands.describe(channel="The channel to add to the list")
    async def add_channel(self, ctx: commands.Context, channel: discord.abc.GuildChannel):
        """Add a channel to the auto scan list. Threads follow their parent channel."""
        async with self.config.guild(ctx.guild).channels() as channels:
            if channel.id not in channels:
                channels.append(channel.id)
        await ctx.send(f"Added {channel.mention} to the channel list.")

    @provenanceset.command(name="removechannel")
    @commands.admin_or_permissions(administrator=True)
    @app_commands.describe(channel="The channel to remove from the list")
    async def remove_channel(self, ctx: commands.Context, channel: discord.abc.GuildChannel):
        """Remove a channel from the auto scan list."""
        async with self.config.guild(ctx.guild).channels() as channels:
            if channel.id in channels:
                channels.remove(channel.id)
        await ctx.send(f"Removed {channel.mention} from the channel list.")
