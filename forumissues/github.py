"""Minimal GitHub App REST client: installation tokens, issues, comments, attachment uploads."""
from __future__ import annotations

import asyncio
import base64
import email.utils
import time
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator, Dict, List, Optional, Set, Tuple

import aiohttp
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

API_VERSION = "2022-11-28"  # supported by GitHub until March 10, 2028
ATTACHMENT_BRANCH = "discord-attachments"
ATTACHMENT_README = "Attachments copied from Discord forum posts by the ForumIssues cog.\n"
# ponytail: Discord's default upload cap; upload through git blobs if bigger files need copying.
MAX_ATTACHMENT_BYTES = 10 << 20

_HINTS = {
    0: "transport failed; the request outcome may be unknown",
    -1: "requests paused by a GitHub rate-limit backoff",
    401: "check the GitHub App ID and private key",
    403: "check the App's Issues and Contents write permissions and rate limits",
    404: "check the repository name and that the GitHub App is installed on it",
    409: "the repository is empty; push an initial commit so attachments can be stored",
    410: "check repository Issues are enabled",
    422: "check configured labels and issue validation limits",
    429: "rate limited; waiting for Retry-After or rate-limit reset",
}


class GitHubError(Exception):
    """status 0: sent, outcome unknown. -1: never sent. Otherwise the HTTP status."""

    def __init__(self, status: int, detail: str = ""):
        self.status = status
        hint = _HINTS.get(status, "request failed; retrying on the next poll")
        super().__init__(detail or (f"GitHub HTTP {status}: {hint}" if status > 0 else f"GitHub {hint}"))

    @property
    def rejected(self) -> bool:
        """True when GitHub definitely did not act on the request, so retrying cannot duplicate it."""
        return self.status == -1 or (400 <= self.status < 500 and self.status != 408)


def parse_time(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def iso(t: datetime) -> str:
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_key(text: str) -> rsa.RSAPrivateKey:
    """The App's PEM key; settings that cannot hold newlines may carry them as a literal \\n."""
    try:
        key = serialization.load_pem_private_key(text.replace("\\n", "\n").encode(), None)
    except (ValueError, TypeError):
        key = None
    if not isinstance(key, rsa.RSAPrivateKey):
        raise ValueError("private_key is not the GitHub App's PEM RSA private key")
    return key


def valid_url(url: Any) -> bool:
    return isinstance(url, str) and url.startswith("https://") and "@" not in url.split("/")[2]


class GitHubApp:
    def __init__(self, session: aiohttp.ClientSession, app_id: str, key: rsa.RSAPrivateKey, base: str):
        self.session = session
        self.app_id = app_id
        self.key = key
        self.base = base.rstrip("/")
        self.blocked_until = 0.0
        self.slug: Optional[str] = None
        self._installations: Dict[str, int] = {}
        self._tokens: Dict[str, Tuple[str, float]] = {}
        self._branch_ready: Set[str] = set()

    def _jwt(self) -> str:
        now = int(time.time())
        # iss is the App ID or Client ID; GitHub accepts either as a string.
        return jwt.encode({"iat": now - 60, "exp": now + 540, "iss": self.app_id}, self.key, algorithm="RS256")

    async def _do(self, method: str, path: str, bearer: str, body: Any = None,
                  params: Optional[dict] = None, repo: str = "") -> Any:
        if time.time() < self.blocked_until:
            raise GitHubError(-1)
        headers = {
            "Authorization": "Bearer " + bearer,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": API_VERSION,
            "User-Agent": "pac-cogs-forumissues",
        }
        try:
            # A 10 MiB upload is ~13 MB of base64, too much for the session's 15s on a slow uplink.
            timeout = aiohttp.ClientTimeout(total=300) if method == "PUT" else self.session.timeout
            async with self.session.request(method, self.base + path, json=body, params=params, headers=headers,
                                            allow_redirects=False, timeout=timeout) as r:
                # Never log response bodies: they can hold user content or credentials.
                if not 200 <= r.status < 300:
                    if r.status == 401:
                        self._tokens.pop(repo, None)
                    # A 403 is a rate limit only when GitHub says so; otherwise it's a permission
                    # problem in one repo and must not pause requests for the others.
                    limited = r.headers.get("Retry-After") or r.headers.get("X-RateLimit-Remaining") == "0"
                    if r.status == 429 or r.status >= 500 or (r.status == 403 and limited):
                        self._backoff(r.headers)
                    raise GitHubError(r.status)
                if r.status == 204:
                    return None
                return await r.json(content_type=None)
        except GitHubError:
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
            raise GitHubError(0) from None

    def _backoff(self, headers: Any) -> None:
        until = time.time() + 60
        retry = headers.get("Retry-After", "")
        try:
            until = time.time() + max(float(retry), 0)
        except ValueError:
            try:
                until = email.utils.parsedate_to_datetime(retry).timestamp()
            except (TypeError, ValueError):
                pass
        reset = headers.get("X-RateLimit-Reset", "")
        if headers.get("X-RateLimit-Remaining") == "0" and reset.isdigit():
            until = max(until, float(reset))
        self.blocked_until = max(self.blocked_until, until)

    async def app_slug(self) -> str:
        """The App's handle: people mention it as @slug, its comments are by slug[bot]."""
        if not self.slug:
            app = await self._do("GET", "/app", self._jwt())
            if not app or not app.get("slug"):
                raise GitHubError(0, "GitHub returned no App slug")
            self.slug = app["slug"]
        return self.slug

    async def token(self, repo: str) -> str:
        """A token scoped to one repository, reused until shortly before its one-hour expiry."""
        cached = self._tokens.get(repo)
        if cached and cached[1] - time.time() > 300:
            return cached[0]
        bearer = self._jwt()
        if repo not in self._installations:
            inst = await self._do("GET", f"/repos/{repo}/installation", bearer)
            self._installations[repo] = int(inst["id"])
        try:
            t = await self._do("POST", f"/app/installations/{self._installations[repo]}/access_tokens",
                               bearer, {"repositories": [repo.split("/", 1)[1]]})
        except GitHubError as e:
            if e.status == 404:
                self._installations.pop(repo, None)  # the App was reinstalled; look it up again
            raise
        if not t or not t.get("token"):
            raise GitHubError(0, "GitHub returned no installation token")
        self._tokens[repo] = (t["token"], parse_time(t["expires_at"]).timestamp())
        return t["token"]

    async def request(self, repo: str, method: str, path: str, body: Any = None,
                      params: Optional[dict] = None) -> Any:
        return await self._do(method, f"/repos/{repo}{path}", await self.token(repo), body, params, repo)

    async def pages(self, repo: str, path: str, params: Optional[dict] = None) -> AsyncIterator[List[dict]]:
        page = 1
        while True:
            items = await self.request(repo, "GET", path, params={**(params or {}), "per_page": 100, "page": page})
            yield items
            if len(items) < 100:
                return
            page += 1

    async def missing_labels(self, repo: str, labels: List[str]) -> List[str]:
        """Checks App access and Issues; returns configured labels the repository lacks."""
        await self.app_slug()
        info = await self.request(repo, "GET", "")
        if not info.get("has_issues"):
            raise GitHubError(410, f"{repo} has Issues disabled")
        available: Set[str] = set()
        async for page in self.pages(repo, "/labels"):
            available.update(label["name"].lower() for label in page)
        return [label for label in labels if label.lower() not in available]

    async def find_marked(self, repo: str, marker: str) -> Optional[dict]:
        """Scans issues directly rather than GitHub search's eventually consistent index."""
        found = None
        async for page in self.pages(repo, "/issues", {"state": "all", "sort": "created", "direction": "desc"}):
            for issue in page:
                if not issue.get("pull_request") and (issue.get("body") or "").endswith("\n\n" + marker):
                    if found:
                        raise GitHubError(0, f"multiple issues in {repo} carry {marker}; repair the mapping manually")
                    found = issue
        return found

    async def issue(self, repo: str, number: int) -> dict:
        issue = await self.request(repo, "GET", f"/issues/{number}")
        if issue.get("number") != number or not valid_url(issue.get("html_url")):
            raise GitHubError(0, "GitHub returned an invalid issue")
        return issue

    async def _ensure_branch(self, repo: str) -> None:
        """Attachments live on an orphan branch: no default-branch history, no workflows to run."""
        if repo in self._branch_ready:
            return
        try:
            await self.request(repo, "GET", f"/git/ref/heads/{ATTACHMENT_BRANCH}")
        except GitHubError as e:
            if e.status != 404:
                raise
            tree = await self.request(repo, "POST", "/git/trees", {"tree": [
                {"path": "README.md", "mode": "100644", "type": "blob", "content": ATTACHMENT_README}]})
            commit = await self.request(repo, "POST", "/git/commits", {
                "message": "Store Discord forum attachments", "tree": tree["sha"], "parents": []})
            await self.request(repo, "POST", "/git/refs", {"ref": "refs/heads/" + ATTACHMENT_BRANCH, "sha": commit["sha"]})
        else:
            # Never commit onto someone else's branch: it could carry workflows that uploads would run.
            try:
                readme = await self.request(repo, "GET", "/contents/README.md", params={"ref": ATTACHMENT_BRANCH})
                content = base64.b64decode(readme.get("content", "")).decode(errors="replace")
            except GitHubError as e:
                if e.status != 404:
                    raise
                content = ""
            if content != ATTACHMENT_README:
                raise GitHubError(0, f"{repo} branch {ATTACHMENT_BRANCH} exists but was not created by this cog; rename it")
        self._branch_ready.add(repo)

    async def upload(self, repo: str, path: str, data: bytes) -> str:
        """Stores a file at a deterministic path, so a retry after a lost response reuses it."""
        await self._ensure_branch(repo)
        try:
            url = (await self.request(repo, "GET", "/contents/" + path, params={"ref": ATTACHMENT_BRANCH}))["html_url"]
        except GitHubError as e:
            if e.status != 404:
                raise
            created = await self.request(repo, "PUT", "/contents/" + path, {
                "message": "Store Discord attachment " + path,
                "content": base64.b64encode(data).decode(), "branch": ATTACHMENT_BRANCH})
            url = created["content"]["html_url"]
        if not valid_url(url):
            raise GitHubError(0, "GitHub returned an invalid attachment URL")
        return url + "?raw=true"

    async def closing_comment(self, repo: str, issue: dict, closed_at: datetime) -> str:
        """The comment the closer posted with the closure, as "Close with comment" does."""
        closer = (issue.get("closed_by") or {}).get("login")
        if not closer:
            return ""
        found = ""
        # since filters by update time, so older comments edited recently can fill several pages.
        async for page in self.pages(repo, f"/issues/{issue['number']}/comments",
                                     {"since": iso(closed_at - timedelta(minutes=1))}):
            for c in page:
                # ponytail: closer + one-minute window; read the timeline API if this ever misattributes.
                if c["user"]["login"] == closer and abs(parse_time(c["created_at"]) - closed_at) <= timedelta(minutes=1):
                    found = c.get("body") or ""
        return found

    async def comments_since(self, repo: str, since: datetime) -> List[dict]:
        out: List[dict] = []
        async for page in self.pages(repo, "/issues/comments", {"sort": "created", "direction": "asc", "since": iso(since)}):
            out.extend(page)
        return out

    async def comment(self, repo: str, number: int, body: str) -> None:
        """Posts body, whose last line is a unique marker, unless a lost earlier attempt already did:
        comment creation has no idempotency key."""
        marker = body.rsplit("\n", 1)[-1]
        async for page in self.pages(repo, f"/issues/{number}/comments"):
            if any((c.get("body") or "").endswith(marker) for c in page):
                return
        await self.request(repo, "POST", f"/issues/{number}/comments", {"body": body.replace("@", "@​")})
