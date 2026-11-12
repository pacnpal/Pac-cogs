"""Self-check for ForumIssues' attachment-branch ownership check.

Run from the repo root: python tests/test_forumissues_branch.py
"""
import asyncio
import base64
import importlib.util
from pathlib import Path

# Load github.py alone: the package __init__ needs Red, this module does not.
_spec = importlib.util.spec_from_file_location(
    "forumissues_github", Path(__file__).resolve().parents[1] / "forumissues" / "github.py")
_github = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_github)
ATTACHMENT_README, GitHubApp, GitHubError = _github.ATTACHMENT_README, _github.GitHubApp, _github.GitHubError

LEGACY = "Attachments copied from Discord forum posts by the ThrillWiki bot.\n"


def app_with_readme(readme):
    """A GitHubApp whose repo already has the attachment branch with the given README (None: no README)."""
    app = GitHubApp.__new__(GitHubApp)
    app._branch_ready = set()
    calls = []

    async def request(repo, method, path, body=None, params=None):
        calls.append((method, path))
        if path.startswith("/git/ref/heads/"):
            return {"object": {"sha": "abc"}}
        if path == "/contents/README.md":
            if readme is None:
                raise GitHubError(404)
            return {"content": base64.encodebytes(readme.encode()).decode()}
        raise AssertionError(f"unexpected {method} {path}")

    app.request = request
    return app, calls


async def main():
    for readme in (ATTACHMENT_README, LEGACY):
        app, calls = app_with_readme(readme)
        await app._ensure_branch("o/r")
        assert "o/r" in app._branch_ready, readme
        assert all(m == "GET" for m, _ in calls), calls  # adopting never writes

    for readme in ("# my project\n", None):
        app, _ = app_with_readme(readme)
        try:
            await app._ensure_branch("o/r")
        except GitHubError as e:
            assert "not created by this cog" in str(e)
        else:
            raise AssertionError(f"foreign branch accepted: {readme!r}")
        assert "o/r" not in app._branch_ready
    print("ok")


asyncio.run(main())
