# ForumIssues

Turns posts in Discord forum channels into GitHub issues through a GitHub App.

When someone opens a post in a watched forum, the cog creates an issue in that forum's repository with the post title, the opening message, its attachments, and a link back to Discord. It adds the forum's labels and replies in the post with the issue link. Replies in the post don't create issues.

People can keep talking to the issue from Discord. A message in the post that mentions the bot becomes an issue comment. An issue comment that mentions the App as `@APP-SLUG` gets posted back into the post and pings the person who opened it. Everything else stays where it was written.

When the issue is closed as completed, the cog tells the poster in the post. If the maintainer closed it with a comment, that comment is quoted. Closing as not planned or duplicate sends nothing. Reopening and completing again sends one more notice.

## Setup

1. Turn on the **Message Content** intent for your bot in the Discord developer portal.
2. [Register a GitHub App](https://docs.github.com/en/apps/creating-github-apps/registering-a-github-app/registering-a-github-app) with no webhook and these repository permissions: **Issues: read and write**, **Contents: read and write**, **Metadata: read-only**. Install it on every repository you want issues in, then generate a private key.
3. Install and load the cog:
    ```
    [p]cog install Pac-cogs forumissues
    [p]load forumissues
    ```
4. As the bot owner, DM the bot `[p]fi app <APP_ID>` with the downloaded `.pem` file attached. The key is stored in Red's shared API tokens under `forumissues`. Red's `[p]set api` can't take the key itself because it splits values on spaces.
5. In each server, give the bot **View Channel**, **Read Message History**, **Send Messages in Threads** and **Manage Threads** on the forum, then run:
    ```
    [p]fi add #bug-reports owner/repo bug "needs triage"
    ```
    Every label has to exist in the repository already. The command checks that, plus the App's access and the bot's permissions, before it saves anything.

For GitHub Enterprise, also run `[p]set api forumissues api_base https://github.example.com/api/v3`.

## Commands

`[p]fi` is short for `[p]forumissues`. These are prefix commands only; there are no slash commands. Admin means a Red admin role or the Manage Server permission.

| Command | Who | What |
| --- | --- | --- |
| `[p]fi add <forum> <owner/repo> [labels...]` | Admin | Watch a forum, or change its repository or labels |
| `[p]fi remove <forum>` | Admin | Stop watching a forum. Existing issue links are kept. Takes a channel ID too, for a forum that was deleted |
| `[p]fi list` | Admin | Show watched forums |
| `[p]fi setup` | Anyone | Show the setup steps |
| `[p]fi app <app_id>` | Owner, DM | Save the App ID (or Client ID) and the attached private key |
| `[p]fi interval <seconds>` | Owner | How often to poll GitHub and retry pending work, for all servers. 10 to 86400. Default 60 |

## How it behaves

Only posts created after a forum is added are picked up, with a five minute allowance for clock skew. Posts made while the bot was offline are found on the next poll, including ones that were archived in the meantime.

Attachments are copied into the repository on an orphan `discord-attachments` branch, because Discord's attachment links expire. The branch shares no history with your default branch and has no workflows, so uploads don't trigger CI. The repository needs at least one commit. If a branch with that name already exists and wasn't made by this cog, the cog refuses to use it. Files over 10 MiB aren't copied and link to the Discord message instead.

Issues, comments and uploads show up on GitHub as `APP-SLUG[bot]`. Any `@` in text copied from Discord gets a zero-width space after it, so Discord users can't ping GitHub users or teams through the App. GitHub doesn't autocomplete App names, so maintainers have to type `@APP-SLUG` in full.

Each poll reads every linked issue once. That's fine for a community server. If you have thousands of open posts, raise the interval.

## When an issue create is uncertain

GitHub has no idempotency key for creating issues. Before sending the request, the cog saves that it's about to try. If the request times out or GitHub answers 5xx, the cog can't know whether the issue was made. It never sends a second create in that case. On every poll it looks through the repository's issues for the hidden `<!-- discord-forum-issue:GUILD_ID:THREAD_ID -->` marker at the end of the body, and picks the issue up if it shows up. Keep that marker intact. Synced comments carry a `<!-- discord-message:MESSAGE_ID -->` marker for the same reason.

For up to an hour after an uncertain create, the cog also holds back GitHub comment relay for that repository, so comments on a recovered issue aren't skipped. After that, relay resumes for the repository's other issues.

If an uncertain create really made nothing, the post stays stuck and the log says so. Check the repository's open and closed issues for the marker first. If there's truly no issue, stop the bot, set that post's `attempted` to `false` in the cog's Config data (`cogs/ForumIssues/settings.json` under Red's data path with the JSON backend), and start it again.

## Data

The cog stores the watched forums, and for each post its title, opening message, the poster's Discord ID and username, the linked issue, and any messages waiting to be relayed. That text is also copied to GitHub, where the cog can't delete it. A Red data deletion request stops the cog from mentioning that user again.
