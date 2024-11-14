# Pac-cogs - Red Discord Bot Cogs Collection

Welcome to **Pac-cogs**, a collection of custom cogs for [Red](https://github.com/Cog-Creators/Red-DiscordBot). These cogs are designed to add extra functionality to your Red bot instance on Discord.

## Cogs Overview

| Cog Name   | Description                                      |
|------------|--------------------------------------------------|
| **Birthday** | Assigns a special birthday role to users and sends a celebratory message with random cake or pie emojis. Features include: automatic role removal at midnight in configurable timezone, custom announcement channels, role-based command permissions, random cake/pie emoji generation, task persistence across bot restarts, and no hierarchy requirements for role assignment. Perfect for automated birthday celebrations! |
| **Overseerr** | Allows interaction with [Overseerr](https://overseerr.dev/) directly from Discord. Users can search for movies or TV shows, request them, and have admins approve requests. Features include: media availability checking, request status tracking, admin role configuration, and direct integration with Overseerr's API. Requires a running Overseerr instance and API key. |
| **VideoArchiver** | A powerful video archiving cog that automatically downloads and reposts videos from monitored channels. Features hardware-accelerated compression (NVIDIA, AMD, Intel, ARM), multi-video processing, role-based permissions, and support for multiple video platforms via yt-dlp. Automatically compresses videos to meet Discord's file size limits while maintaining quality. |

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

- **Birthday**: No additional requirements. Just configure the birthday role, timezone, and allowed roles after installation.

- **Overseerr**: Requires a running [Overseerr](https://overseerr.dev/) instance and API key. You'll need to configure the Overseerr URL and API key after installation using:
    ```bash
    [p]overseerr url <your-overseerr-url>
    [p]overseerr apikey <your-api-key>
    ```

- **VideoArchiver**: The cog requires FFmpeg for video processing. The cog will attempt to download and manage FFmpeg automatically if it's not found on your system. The required Python packages (yt-dlp, ffmpeg-python, requests) will be installed automatically during cog installation.

For more details on setting up and managing Red, visit the [Red documentation](https://docs.discord.red).
