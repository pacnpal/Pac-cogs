"""Discord forum posts -> GitHub issues, with mention-based comment sync and completion replies."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Union

import aiohttp
import discord
from redbot.core import Config, commands
from redbot.core.bot import Red

from .github import MAX_ATTACHMENT_BYTES, GitHubApp, GitHubError, load_key, parse_time, valid_url
from .text import code_safe, fit, md_text, mentions, neutralize, quote, safe_filename, strip_mention

log = logging.getLogger("red.pac-cogs.forumissues")

TOKEN_SERVICE = "forumissues"
# Overlap for activation/archive cutoffs, so a host clock ahead of Discord does not drop new posts.
CLOCK_SKEW = timedelta(minutes=5)
# How long an uncertain create holds its repo's comment cursor, so a recovered issue's comments
# wait instead of being passed. After that, the post likely needs manual repair (see README).
RECOVERY_HOLD = 3600
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
NEEDED_PERMS = ("view_channel", "read_message_history", "send_messages_in_threads", "manage_threads")


def issue_marker(p: dict) -> str:
    return f"<!-- discord-forum-issue:{p['guild_id']}:{p['thread_id']} -->"


def message_url(p: dict, message_id: Union[int, str]) -> str:
    return f"https://discord.com/channels/{p['guild_id']}/{p['thread_id']}/{message_id}"


class Pending(Exception):
    """A step that cannot finish yet; the next poll retries it."""


def discord_hint(e: Exception) -> str:
    if isinstance(e, discord.HTTPException):
        return (f"Discord HTTP {e.status} (code {e.code}): check View Channel, Read Message History, "
                "Send Messages in Threads, and Manage Threads permissions")
    return f"Discord request failed: {type(e).__name__}"


class ForumIssues(commands.Cog):
    """Turn posts in Discord forums into GitHub issues, and tell posters when they are resolved."""

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=0x6F72756D49, force_registration=True)
        self.config.register_global(poll_interval=60, blocked_until=0.0, repos={})
        # forums: {channel_id: {repo, labels, since, scanned}}; posts: {thread_id: post}
        self.config.register_guild(forums={}, posts={})
        self.session: Optional[aiohttp.ClientSession] = None
        self.gh: Optional[GitHubApp] = None
        self.lock = asyncio.Lock()
        self.queue: "asyncio.Queue[int]" = asyncio.Queue(maxsize=128)
        self.task: Optional[asyncio.Task] = None
        # Threads seen by discovery's archive scan. Archived threads leave the cache, but the scan
        # returns every thread re-archived since the last poll, with its last_message_id.
        self.seen: Dict[int, discord.Thread] = {}

    async def cog_load(self) -> None:
        self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15))
        self.task = asyncio.create_task(self.worker())

    async def cog_unload(self) -> None:
        if self.task:
            self.task.cancel()
        if self.session:
            await self.session.close()

    async def red_delete_data_for_user(self, *, requester: str, user_id: int) -> None:
        # Issue text already on GitHub is outside the bot's reach; stop pinging the user from Discord.
        async with self.lock:
            for gid, data in (await self.config.all_guilds()).items():
                for tid, p in data.get("posts", {}).items():
                    if p.get("creator_id") == str(user_id):
                        await self.config.guild_from_id(gid).posts.set_raw(tid, "creator_id", value=None)

    # ---- GitHub client -------------------------------------------------------------------

    async def github(self) -> Optional[GitHubApp]:
        if self.gh is None:
            tokens = await self.bot.get_shared_api_tokens(TOKEN_SERVICE)
            if not tokens.get("app_id") or not tokens.get("private_key"):
                return None
            base = tokens.get("api_base", "https://api.github.com")
            if not base.startswith("https://") or any(c in base for c in "?#@"):
                raise ValueError("api_base must be an HTTPS URL without credentials, query, or fragment")
            self.gh = GitHubApp(self.session, tokens["app_id"], load_key(tokens["private_key"]), base)
            self.gh.blocked_until = await self.config.blocked_until()
        return self.gh

    @commands.Cog.listener()
    async def on_red_api_tokens_update(self, service_name: str, api_tokens: Dict[str, str]) -> None:
        if service_name == TOKEN_SERVICE:
            self.gh = None

    # ---- Discord events --------------------------------------------------------------------

    def enqueue(self, thread_id: int) -> None:
        try:
            self.queue.put_nowait(thread_id)
        except asyncio.QueueFull:
            pass  # the next poll recovers whatever overflowed

    async def watched(self, channel: Any) -> bool:
        if not isinstance(channel, discord.Thread) or channel.guild is None:
            return False
        if await self.bot.cog_disabled_in_guild(self, channel.guild):
            return False
        return str(channel.parent_id) in await self.config.guild(channel.guild).forums()

    @commands.Cog.listener()
    async def on_thread_create(self, thread: discord.Thread) -> None:
        if await self.watched(thread):
            self.enqueue(thread.id)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        # Opening messages create issues; replies mentioning the bot are relayed to the issue.
        me = self.bot.user
        if message.id != message.channel.id and (me is None or me not in message.mentions):
            return
        if await self.watched(message.channel):
            self.enqueue(message.channel.id)

    # ---- worker ------------------------------------------------------------------------------

    async def worker(self) -> None:
        await self.bot.wait_until_red_ready()
        thread_id: Optional[int] = None
        discover = True
        next_poll = 0.0
        while True:
            if discover:
                next_poll = time.monotonic() + await self.config.poll_interval()
            try:
                await self.cycle(thread_id, discover)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("forum issue cycle failed; next poll will retry")
            try:
                thread_id = await asyncio.wait_for(self.queue.get(), max(0.0, next_poll - time.monotonic()))
                discover = False
            except asyncio.TimeoutError:
                thread_id, discover = None, True

    async def save(self, p: dict) -> None:
        await self.config.guild_from_id(int(p["guild_id"])).posts.set_raw(p["thread_id"], value=p)

    async def save_backoff(self) -> None:
        if self.gh and self.gh.blocked_until > await self.config.blocked_until():
            await self.config.blocked_until.set(self.gh.blocked_until)

    async def step(self, coro: Any, what: str, thread_id: str = "") -> None:
        """Runs one unit of work; a failure is logged and retried on the next poll."""
        try:
            await coro
        except (GitHubError, Pending, discord.HTTPException) as e:
            msg = discord_hint(e) if isinstance(e, discord.HTTPException) else str(e)
            log.warning("%s pending (thread %s); next poll will retry: %s", what, thread_id or "-", msg)
        except Exception:
            log.exception("%s pending (thread %s); next poll will retry", what, thread_id or "-")
        await self.save_backoff()

    async def cycle(self, thread_id: Optional[int], discover: bool) -> None:
        async with self.lock:
            gh = await self.github()
            if gh is None:
                return
            guilds = {gid: d for gid, d in (await self.config.all_guilds()).items() if d.get("forums")}
            for gid in list(guilds):
                guild = self.bot.get_guild(gid)
                if guild is None or await self.bot.cog_disabled_in_guild(self, guild):
                    del guilds[gid]
            if thread_id is not None:
                channel = await self.channel(thread_id)
                if isinstance(channel, discord.Thread) and channel.guild.id in guilds:
                    await self.register(guilds[channel.guild.id], channel)
                if not any(str(thread_id) in d["posts"] for d in guilds.values()):
                    return  # a bot mention outside linked posts; polling covers other pending work
            if discover:
                for gid, data in guilds.items():
                    await self.step(self.discover(self.bot.get_guild(gid), data), "forum discovery")
            for data in guilds.values():
                for p in data["posts"].values():
                    if not discover and p["thread_id"] != str(thread_id):
                        continue  # an event cycle handles only its own post; polling covers the rest
                    forum = data["forums"].get(p["forum_id"])
                    if forum is None:
                        continue  # a removed forum is no longer monitored
                    await self.step(self.process(gh, p, forum), "forum post", p["thread_id"])
                    # Separate step, so a deleted thread cannot hold back a resolution notice.
                    await self.step(self.sync(gh, p), "comment sync", p["thread_id"])
            # Sweep after the posts, so an issue recovered from a lost create response is mapped
            # before the comment cursor passes its comments.
            if discover:
                await self.step(self.sweep(gh, guilds), "GitHub comment sync")

    async def channel(self, channel_id: Union[int, str]) -> Any:
        channel = self.bot.get_channel(int(channel_id))
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(int(channel_id))
            except discord.HTTPException:
                return None
        return channel

    async def register(self, data: dict, thread: discord.Thread) -> None:
        forum = data["forums"].get(str(thread.parent_id))
        tid = str(thread.id)
        if tid in data["posts"]:
            self.seen[thread.id] = thread  # only linked posts are synced, so only they are kept
            return
        if forum is None or thread.type != discord.ChannelType.public_thread:
            return
        # ponytail: skew beyond CLOCK_SKEW can still miss posts; keep host clocks synchronized.
        if discord.utils.snowflake_time(thread.id).timestamp() < forum["since"] - CLOCK_SKEW.total_seconds():
            return
        p = {"guild_id": str(thread.guild.id), "forum_id": str(thread.parent_id), "thread_id": tid,
             "title": thread.name, "repo": forum["repo"], "labels": forum["labels"], "creator_id": None, "body": "", "loaded": False,
             "attempted": False, "issue_number": 0, "issue_url": "", "announced": False,
             "notified_closures": [], "resolution": None, "cursor": tid, "to_github": [], "to_discord": []}
        data["posts"][tid] = p
        await self.save(p)

    async def discover(self, guild: discord.Guild, data: dict) -> None:
        """Finds posts missed while offline: active threads guild-wide, then each forum's archive."""
        for thread in await guild.active_threads():
            await self.register(data, thread)
        for cid, forum in data["forums"].items():
            channel = guild.get_channel(int(cid))
            if not isinstance(channel, discord.ForumChannel):
                log.warning("configured forum %s in guild %s is missing or not a forum", cid, guild.id)
                continue
            since = max(forum["since"], forum.get("scanned", 0)) - CLOCK_SKEW.total_seconds()
            started = time.time()
            async for thread in channel.archived_threads(limit=None):
                if thread.archive_timestamp.timestamp() < since:
                    break
                await self.register(data, thread)
            forum["scanned"] = started
            await self.config.guild(guild).forums.set_raw(cid, "scanned", value=started)

    # ---- forum post -> issue -> resolution --------------------------------------------------

    async def process(self, gh: GitHubApp, p: dict, forum: dict) -> None:
        # Both are fixed at registration: changing a forum's repo must not send the new repo's
        # labels to an issue pending in the old one.
        repo, labels = p["repo"], p["labels"]
        if not p["loaded"]:
            thread = await self.channel(p["thread_id"])
            if not isinstance(thread, discord.Thread):
                raise Pending("the forum post is deleted or no longer visible to the bot")
            m = await thread.fetch_message(thread.id)
            p["creator_id"] = str(m.author.id)
            url = message_url(p, p["thread_id"])
            files = await self.attachments(gh, p, url, m.attachments)
            p["body"] = (f"{quote(m.content)}{files}\n\n"
                         f"Posted by Discord user `{code_safe(m.author.name)}` (ID `{m.author.id}`).\n\n"
                         f"[Original Discord post]({url})\n\n{issue_marker(p)}")
            p["loaded"] = True
            await self.save(p)
        if not p["issue_number"]:
            if p["attempted"]:
                issue = await gh.find_marked(repo, issue_marker(p))
                if issue is None:
                    raise Pending("GitHub create outcome is uncertain and no matching issue exists yet; "
                                         "automatic re-creation is paused to prevent duplicates (see README)")
            else:
                await gh.token(repo)  # a failed mint sends no POST, so it must not mark an attempt
                # Commit the intent before the POST: a crash after GitHub accepts it must never re-send.
                p["attempted"], p["attempted_at"] = True, time.time()
                await self.save(p)
                try:
                    issue = await gh.request(repo, "POST", "/issues", {
                        "title": neutralize(p["title"]), "body": neutralize(p["body"]), "labels": labels})
                except GitHubError as e:
                    if e.rejected:
                        p["attempted"] = False
                        await self.save(p)
                    raise
            if not issue or int(issue.get("number") or 0) <= 0 or not valid_url(issue.get("html_url")):
                raise GitHubError(0, "GitHub returned an invalid issue; reconcile before retrying")
            p["issue_number"], p["issue_url"] = issue["number"], issue["html_url"]
            await self.save(p)
        issue = await gh.issue(repo, p["issue_number"])
        if not p["announced"]:
            # GitHub silently drops labels the caller cannot apply; the mapping is saved first, so
            # repairing labels can never produce a second issue. Add only what is missing.
            if self.missing(issue, labels):
                await gh.request(repo, "POST", f"/issues/{p['issue_number']}/labels", {"labels": labels})
                issue = await gh.issue(repo, p["issue_number"])
                missing = self.missing(issue, labels)
                if missing:
                    raise Pending(f"issue #{issue['number']} is missing labels {missing}; check the App's Issues write access")
            await self.notify(p, f"GitHub issue created: <{p['issue_url']}>\n"
                                 f"Mention {self.bot.user.mention} in this post to add your message to the issue.", False)
            p["announced"] = True
            await self.save(p)
        # Only completed closures notify; not_planned, duplicate and null reasons never do.
        closed_at = issue.get("closed_at")
        if issue.get("state") != "closed" or issue.get("state_reason") != "completed" or not closed_at \
                or closed_at in p["notified_closures"]:
            return
        if not p["resolution"] or p["resolution"]["closed_at"] != closed_at:
            when = parse_time(closed_at)
            comment = (await gh.closing_comment(repo, issue, when)).strip()
            ping = f"<@{p['creator_id']}> " if p["creator_id"] else ""
            content = f"{ping}Your issue was resolved: <{p['issue_url']}>\nCompleted at <t:{int(when.timestamp())}:F>."
            if comment:
                content += "\n\n" + quote(comment)
            # Frozen before sending, so an edited closing comment cannot cause a second reply.
            p["resolution"] = {"closed_at": closed_at, "content": fit(content)}
            await self.save(p)
        await self.notify(p, p["resolution"]["content"], True)
        p["notified_closures"].append(closed_at)
        p["resolution"] = None
        await self.save(p)

    @staticmethod
    def missing(issue: dict, labels: List[str]) -> List[str]:
        have = {label["name"].lower() for label in issue.get("labels", [])}
        return [label for label in labels if label.lower() not in have]

    async def attachments(self, gh: GitHubApp, p: dict, url: str, files: List[discord.Attachment]) -> str:
        """Copies files into the repository: Discord's signed attachment URLs expire."""
        body = ""
        for a in files:
            name = md_text(a.filename)
            if a.size > MAX_ATTACHMENT_BYTES:
                body += f"\n\nAttachment (too large to copy): [{name}]({url})"
                continue
            link = await gh.upload(p["repo"], f"{p['thread_id']}/{a.id}-{safe_filename(a.filename)}", await a.read())
            image = (a.content_type or "").startswith("image/")
            body += f"\n\nAttachment: {'!' if image else ''}[{name}]({link})"
        return body

    async def notify(self, p: dict, content: str, mention: bool) -> None:
        """Sends content once: a lost response or restart finds the earlier copy in the history."""
        me = self.bot.user
        thread = await self.channel(p["thread_id"])
        if not isinstance(thread, discord.Thread):
            raise Pending("the forum post is deleted or no longer visible to the bot")
        async for m in thread.history(limit=None):
            if m.author.id == me.id and m.content == content:
                return
        if thread.archived and thread.locked:
            await thread.edit(archived=False)  # sending unarchives only unlocked posts
        users = [discord.Object(int(p["creator_id"]))] if mention and p["creator_id"] else False
        nonce = hashlib.sha256(f"{p['thread_id']}:{content}".encode()).hexdigest()[:24]
        await thread.send(content, nonce=nonce,
                          allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=users))

    # ---- comment sync -----------------------------------------------------------------------

    async def sync(self, gh: GitHubApp, p: dict) -> None:
        """Relays new messages that mention the bot, then delivers both outboxes."""
        if not p["announced"]:
            return
        thread = self.bot.get_channel(int(p["thread_id"])) or self.seen.get(int(p["thread_id"]))
        last = getattr(thread, "last_message_id", None)
        if isinstance(thread, discord.Thread) and last and last > int(p["cursor"]):
            me = self.bot.user
            async for m in thread.history(limit=None, after=discord.Object(int(p["cursor"])), oldest_first=True):
                if not m.author.bot and me in m.mentions:
                    p["to_github"].append(await self.relay(gh, p, m))
                    p["cursor"] = str(m.id)
                    await self.save(p)
                p["cursor"] = str(m.id)
            await self.save(p)
        while p["to_github"]:
            await gh.comment(p["repo"], p["issue_number"], p["to_github"][0])
            p["to_github"].pop(0)
            await self.save(p)
        while p["to_discord"]:
            await self.notify(p, p["to_discord"][0], True)  # pings the post's creator
            p["to_discord"].pop(0)
            await self.save(p)

    async def relay(self, gh: GitHubApp, p: dict, m: discord.Message) -> str:
        me = self.bot.user.id
        m.content = m.content.replace(f"<@{me}>", "").replace(f"<@!{me}>", "")
        try:
            del m._cs_clean_content  # discord.py caches clean_content; render it from the new content
        except AttributeError:
            pass
        url = message_url(p, m.id)
        files = await self.attachments(gh, p, url, m.attachments)
        return (f"{quote(m.clean_content)}{files}\n\nDiscord user `{code_safe(m.author.name)}` "
                f"(ID `{m.author.id}`) [wrote in the forum post]({url}).\n\n<!-- discord-message:{m.id} -->")

    async def sweep(self, gh: GitHubApp, guilds: Dict[int, dict]) -> None:
        """Queues issue comments that mention the App for their linked Discord posts."""
        slug = await gh.app_slug()
        by_repo: Dict[str, List[dict]] = {}
        for data in guilds.values():
            for p in data["posts"].values():
                if p["forum_id"] in data["forums"]:
                    by_repo.setdefault(p["repo"], []).append(p)
        repos = await self.config.repos()
        hint = f"\n-# Mention {self.bot.user.mention} in this post to reply on GitHub."
        for repo, posts in by_repo.items():
            if any(p["attempted"] and not p["issue_number"] and time.time() - p.get("attempted_at", 0) < RECOVERY_HOLD
                   for p in posts):
                continue  # hold the cursor briefly so a recovered issue's comments wait, not drop
            state = repos.setdefault(repo, {"cursor": 0, "since": time.time()})
            since = datetime.fromtimestamp(state["since"], timezone.utc)
            # since is exclusive and second-precise; overlap it, the ID cursor drops repeats.
            for c in sorted(await gh.comments_since(repo, since - timedelta(minutes=1)), key=lambda c: c["id"]):
                created = parse_time(c["created_at"])
                if c["id"] <= state["cursor"] or created < since:
                    continue  # already checked, or an older comment edited since
                number = int(c["issue_url"].rsplit("/", 1)[1])
                login = c["user"]["login"]
                body = c.get("body") or ""
                # The App's own comments carry Discord text and must not echo back.
                if login.lower() != f"{slug}[bot]".lower() and mentions(slug, body):
                    for p in posts:
                        if p["issue_number"] == number:
                            ping = f"<@{p['creator_id']}> " if p["creator_id"] else ""
                            content = f"{ping}**{login}** commented on GitHub: <{c['html_url']}>\n{quote(strip_mention(slug, body))}"
                            p["to_discord"].append(fit(content, hint))
                            await self.save(p)
                state["cursor"], state["since"] = c["id"], created.timestamp()
            await self.config.repos.set_raw(repo, value=state)

    # ---- commands -----------------------------------------------------------------------------

    @commands.group(name="forumissues", aliases=["fi"])
    async def fi(self, ctx: commands.Context) -> None:
        """Turn forum posts into GitHub issues."""

    @fi.command(name="app")
    @commands.is_owner()
    @commands.dm_only()
    async def fi_app(self, ctx: commands.Context, app_id: str) -> None:
        """Connect the GitHub App: give its App ID (or Client ID) and attach its private key `.pem` file."""
        if not ctx.message.attachments:
            return await ctx.send("Attach the App's private key `.pem` file to this command.")
        pem = (await ctx.message.attachments[0].read()).decode(errors="replace")
        try:
            load_key(pem)
        except ValueError as e:
            return await ctx.send(str(e))
        await self.bot.set_shared_api_tokens(TOKEN_SERVICE, app_id=app_id.strip(), private_key=pem)
        try:
            await ctx.message.delete()
        except discord.HTTPException:
            pass  # bots cannot delete DM messages from others; the key stays only in this DM
        await ctx.send("GitHub App credentials saved. You can delete your message with the key.")

    @fi.command(name="add")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def fi_add(self, ctx: commands.Context, forum: discord.ForumChannel, repo: str, *labels: str) -> None:
        """Watch a forum; new posts become issues in `owner/repo` with the given labels.

        Running it again for the same forum changes its repository or labels.
        Quote labels that contain spaces: `[p]fi add #bugs owner/repo bug "needs triage"`
        """
        labels_list = list(dict.fromkeys(label.strip() for label in labels if label.strip()))
        if not REPO_RE.match(repo) or ".." in repo:
            return await ctx.send("Repository must be `owner/name`.")
        if any(len(label) > 50 for label in labels_list):
            return await ctx.send("GitHub labels are at most 50 characters.")
        if not self.bot.intents.message_content:
            return await ctx.send("The bot needs the Message Content intent to read forum posts.")
        perms = forum.permissions_for(ctx.guild.me)
        lacking = [name for name in NEEDED_PERMS if not getattr(perms, name)]
        if lacking:
            return await ctx.send(f"I need these permissions in {forum.mention}: {', '.join(lacking)}.")
        try:
            gh = await self.github()
        except ValueError as e:
            return await ctx.send(f"GitHub App credentials are invalid: {e}")
        if gh is None:
            return await ctx.send(f"Set the GitHub App credentials first; see `{ctx.clean_prefix}fi setup`.")
        async with ctx.typing():
            try:
                missing = await gh.missing_labels(repo, labels_list)
            except GitHubError as e:
                return await ctx.send(f"Could not use `{repo}`: {e}")
            finally:
                await self.save_backoff()
        if missing:
            return await ctx.send(f"These labels do not exist in `{repo}`: {', '.join(missing)}. Create them first.")
        async with self.lock:
            async with self.config.guild(ctx.guild).forums() as forums:
                old = forums.get(str(forum.id), {})
                forums[str(forum.id)] = {"repo": repo, "labels": labels_list,
                                         "since": old.get("since", time.time()), "scanned": old.get("scanned", 0)}
            async with self.config.repos() as repos:
                repos.setdefault(repo, {"cursor": 0, "since": time.time()})
        await ctx.send(f"New posts in {forum.mention} will become issues in `{repo}`"
                       + (f" labelled {', '.join(labels_list)}." if labels_list else "."))

    @fi.command(name="remove")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def fi_remove(self, ctx: commands.Context, forum: Union[discord.ForumChannel, int]) -> None:
        """Stop watching a forum. Its existing issue links are kept."""
        cid = str(getattr(forum, "id", forum))
        async with self.lock:
            async with self.config.guild(ctx.guild).forums() as forums:
                removed = forums.pop(cid, None)
        await ctx.send("Stopped watching that forum." if removed else "That forum is not watched.")

    @fi.command(name="list")
    @commands.guild_only()
    @commands.admin_or_permissions(manage_guild=True)
    async def fi_list(self, ctx: commands.Context) -> None:
        """Show watched forums."""
        forums = await self.config.guild(ctx.guild).forums()
        if not forums:
            return await ctx.send("No forums are watched.")
        lines = [f"<#{cid}> → `{f['repo']}`" + (f" ({', '.join(f['labels'])})" if f["labels"] else "")
                 for cid, f in forums.items()]
        await ctx.send("\n".join(lines), allowed_mentions=discord.AllowedMentions.none())

    @fi.command(name="setup")
    async def fi_setup(self, ctx: commands.Context) -> None:
        """How to connect a GitHub App."""
        p = ctx.clean_prefix
        await ctx.send(
            "1. Register a GitHub App (no webhook) with repository permissions **Issues: read & write**, "
            "**Contents: read & write** and **Metadata: read**, and install it on each destination repository.\n"
            f"2. In a DM with the bot, the owner runs `{p}fi app <APP_ID>` with the App's private key `.pem` attached. "
            f"GitHub Enterprise: also run `{p}set api {TOKEN_SERVICE} api_base https://HOST/api/v3`.\n"
            f"3. Here, run `{p}fi add #forum owner/repo [labels...]`.")

    @fi.command(name="interval")
    @commands.is_owner()
    async def fi_interval(self, ctx: commands.Context, seconds: commands.Range[int, 10, 86400]) -> None:
        """Set how often pending work and linked issues are checked (all servers)."""
        await self.config.poll_interval.set(seconds)
        await ctx.send(f"Polling every {seconds} seconds from the next cycle.")

