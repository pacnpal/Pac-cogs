# Birthday Cog for Red-DiscordBot

Give someone a birthday role until midnight in your server's timezone, and throw them a party: a random celebratory announcement, a pile of cakes (or pie, or a rare legendary cake drop), and a 🎉 reaction for everyone to join in on. Works with prefix commands, slash commands and right-click context menus.

Requires Red-DiscordBot 3.5+ and Python 3.9+.

## Installation

```
[p]repo add Pac-cogs https://github.com/pacnpal/Pac-cogs
[p]cog install Pac-cogs birthday
[p]load birthday
```

To use slash commands and the context menus (this enables both):

```
[p]slash enablecog birthday
[p]slash sync
```

Replace `[p]` with your bot's prefix.

## Setup

Admins, or anyone with Manage Server, configure the cog with `[p]birthdayset` (or `/birthdayset`):

| Command | What it does |
| --- | --- |
| `birthdayset role @Birthday` | Set the role to give. The bot's top role must be above it. |
| `birthdayset timezone America/New_York` | When "midnight" is. Slash command autocompletes. Default `UTC`. |
| `birthdayset channel #birthdays` | Where to announce. Leave empty to announce wherever the command is used. |
| `birthdayset allowrole @Party Planners` | Let a role give birthday roles. |
| `birthdayset disallowrole @Party Planners` | Take that permission away. |
| `birthdayset message <text>` | Custom announcement. Placeholders: `{mention}` `{name}` `{server}` `{cakes}`. Leave empty to go back to the random built-in messages. |
| `birthdayset test` | Preview the announcement without giving a role. |
| `birthdayset settings` | Show the current settings and flag permission problems. |

Server mods/admins (Red's `[p]set addmodrole` / `addadminrole`) and anyone with Manage Roles can always give birthday roles. Allowed roles add to that list.

## Usage

- `[p]birthday @User` or `/birthday`: give the role and announce it. The role comes off at the next midnight. Giving it again on the same day just tells you the party is already on.
- `[p]removebirthday @User` or `/removebirthday`: end the party early.
- `[p]bdaycheck` or `/bdaycheck`: list who's celebrating and when their role comes off.
- Right-click a member → Apps → **Give Birthday Role** / **Remove Birthday Role**.

## How removal works

Every member's expiry is saved as a timestamp, and the bot checks once a minute, so several birthdays on the same day are all handled and nothing is lost across restarts. If the bot was offline at midnight, the role comes off as soon as it's back. Changing the timezone doesn't move parties that have already started.

## Upgrading from earlier versions

The setup commands moved under `birthdayset` so they no longer clash with other cogs:

| Old | New |
| --- | --- |
| `setrole` | `birthdayset role` |
| `settimezone` | `birthdayset timezone` |
| `setchannel` | `birthdayset channel` |
| `birthdayallowrole` | `birthdayset allowrole` |
| `birthdayremoverole` | `birthdayset disallowrole` |
| `status` | `birthdayset settings` |

Existing settings and running parties carry over.

## Support

Open an issue on the [GitHub repository](https://github.com/pacnpal/Pac-cogs).
