# Pac-cogs - Red Discord Bot Cogs Collection

Welcome to **Pac-cogs**, a collection of custom cogs for [Red](https://github.com/Cog-Creators/Red-DiscordBot). These cogs are designed to add extra functionality to your Red bot instance on Discord.

## Installation

To install the cogs in this repository, follow these steps:

1. Ensure you have [Red](https://github.com/Cog-Creators/Red-DiscordBot) set up.
2. Add this repository to your Red instance:
    ```bash
    [p]repo add Pac-cogs https://github.com/pacnpal/Pac-cogs
    ```
3. Install the desired cog:

    ```bash
    # For Birthday cog:
    [p]cog install Pac-cogs birthday

    # For ForumIssues cog:
    [p]cog install Pac-cogs forumissues

    # For Overseerr cog:
    [p]cog install Pac-cogs overseerr

    # For Provenance cog:
    [p]cog install Pac-cogs provenance

    # For ThrillWiki cog:
    [p]cog install Pac-cogs thrillwiki

    # For VideoArchiver cog:
    [p]cog install Pac-cogs videoarchiver
    ```

4. Load the installed cog:

    ```bash
    # For Birthday cog:
    [p]load birthday

    # For ForumIssues cog:
    [p]load forumissues

    # For Overseerr cog:
    [p]load overseerr

    # For Provenance cog:
    [p]load provenance

    # For ThrillWiki cog:
    [p]load thrillwiki

    # For VideoArchiver cog:
    [p]load videoarchiver
    ```

Replace `[p]` with your bot's prefix.

All cogs target Red-DiscordBot 3.5 (tested on 3.5.24). Slash commands and context menus must be enabled with `[p]slash enablecog <cogname>` (e.g. `birthday`) and then `[p]slash sync`.

### Additional Requirements

- **Birthday**: No extra setup beyond `[p]birthdayset role @Role`. See [birthday/README.md](birthday/README.md). Supports prefix commands, slash commands and context menus.

- **ForumIssues**: Needs a GitHub App installed on the destination repositories and the bot's Message Content intent. Run `[p]fi setup` after loading it. See [forumissues/README.md](forumissues/README.md).

- **Overseerr**: Requires a running [Overseerr](https://overseerr.dev/) instance and API key. You'll need to configure the Overseerr URL and API key after installation using:
    ```bash
    [p]seturl <your-overseerr-url>
    [p]setapikey <your-api-key>
    ```

- **Provenance**: Requires an OpenAI API key with access to the Content Provenance API, set with `[p]set api openai api_key,<your key>`. Avatar scanning needs the Server Members intent enabled in the Discord Developer Portal. It only detects OpenAI's C2PA Content Credentials and SynthID watermark. See the [Provenance README](provenance/README.md) for details.

- **ThrillWiki**: No setup. It reads the public [ThrillWiki](https://www.thrillwiki.com/) API, so there's no key or URL to configure. Try `[p]tw ride steel vengeance` once it's loaded. For the slash commands, run `[p]slash enable thrillwiki` and then `[p]slash sync`. See [thrillwiki/README.md](thrillwiki/README.md) for the full command list.

- **VideoArchiver**: Needs FFmpeg. If it isn't on the system, the cog downloads its own copy the first time it starts. Red installs the Python packages (yt-dlp, ffmpeg-python and the rest) when you install the cog. Set an archive channel with `[p]settings setchannel #channel` before it'll post anything. See [videoarchiver/README.md](videoarchiver/README.md) for the full command list.
