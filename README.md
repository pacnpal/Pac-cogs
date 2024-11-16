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
    [p]cog install Pac-cogs videoarchiver
    ```
4. Load the installed cog:
    ```bash
    [p]load videoarchiver
    ```


3. Install the desired cog:

    ```bash
    # For Birthday cog:
    [p]cog install Pac-cogs birthday

    # For Overseerr cog:
    [p]cog install Pac-cogs overseerr

    # For VideoArchiver cog:
    [p]cog install Pac-cogs videoarchiver
    ```

4. Load the installed cog:

    ```bash
    # For Birthday cog:
    [p]load birthday

    # For Overseerr cog:
    [p]load overseerr

    # For VideoArchiver cog:
    [p]load videoarchiver
    ```

Replace `[p]` with your bot's prefix.

### Additional Requirements

- **Birthday**: No additional requirements. Just configure the birthday role, timezone, and allowed roles after installation. Supports both traditional commands, slash commands, and context menu interactions.

- **Overseerr**: Requires a running [Overseerr](https://overseerr.dev/) instance and API key. You'll need to configure the Overseerr URL and API key after installation using:
    ```bash
    [p]overseerr url <your-overseerr-url>
    [p]overseerr apikey <your-api-key>
    ```

- **VideoArchiver**: The cog requires FFmpeg for video processing. The cog will attempt to download and manage FFmpeg automatically if it's not found on your system. The required Python packages (yt-dlp, ffmpeg-python, requests) will be installed automatically during cog installation.

## VideoArchiver Commands and Features

The VideoArchiver cog now comes with enhanced features and a comprehensive set of slash commands for easy management.

### Default Behavior
- Video archiving is enabled by default for new servers
- All channels are monitored by default (can be restricted using commands)
- All users can trigger archiving by default (can be restricted using commands)
- All video sites are supported by default (can be restricted using commands)

### Core Commands
- `/archiver settings` - View all current settings
- `/archiver enable`, `/archiver disable` - Toggle video archiving
- `/archiver queue` - View the current processing queue

### Channel Management
- `/archiver setchannel` - Set the archive channel
- `/archiver setlog` - Set the log channel
- `/archiver addchannel` - Add a channel to monitor
- `/archiver removechannel` - Remove a channel from monitoring

### Video Settings
