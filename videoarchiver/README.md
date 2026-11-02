# VideoArchiver Cog for Red-DiscordBot

A powerful video archiving cog that automatically downloads and reposts videos from monitored channels. Features hardware-accelerated compression, multi-video processing, and support for multiple video platforms.

## Features

- **Automatic Video Processing**
  - Monitors specified channels for videos
  - Supports multiple video platforms through yt-dlp
  - Hardware-accelerated compression (NVIDIA, AMD, Intel, ARM)
  - Configurable video quality and format
  - Automatic file size optimization for Discord limits
  - Default maximum file size: 8MB
  - Default video format: MP4
  - Default video quality: High
  - Support for MP4, WebM, and MKV formats

- **Video Archive Database**
  - Track and store archived video information
  - Query archived videos by original URL
  - Get Discord links for previously archived videos
  - Optional database functionality (disabled by default)
  - Automatic database management and cleanup
  - Persistent video history tracking
  - URL-based video lookup

- **Modular Queue System**
  - Priority-based processing with state persistence
  - Efficient resource management and monitoring
  - Real-time performance metrics and health checks
  - Automatic cleanup and memory optimization
  - Default concurrent downloads: 2 (configurable 1-5)
  - Maximum queue size: 1000 items
  - Automatic retry on failures (3 attempts with 5-second delay)
  - Queue state persistence across bot restarts
  - Enhanced error recovery

- **Progress Tracking**
  - Real-time download progress monitoring
  - Compression progress tracking
  - Hardware acceleration statistics
  - Detailed error tracking and analysis
  - Memory usage monitoring
  - Success rate calculations
  - Automatic cleanup of temporary files
  - Enhanced logging capabilities

- **Channel Management**
  - Flexible channel monitoring (specific channels or all)
  - Separate archive, notification, and log channels
  - Customizable message templates
  - Configurable message duration (0-168 hours)
  - Enhanced error logging

- **Access Control**
  - Role-based permissions
  - Site-specific enabling/disabling
  - Admin-only configuration commands
  - Per-guild settings
  - Enhanced permission checks

## Installation

1. Install the cog:
```bash
[p]repo add Pac-cogs https://github.com/pacnpal/Pac-cogs
[p]cog install Pac-cogs videoarchiver
```

2. Load the cog:
```bash
[p]load videoarchiver
```

## Commands

Every command works as a prefix command and as a slash command. Red keeps slash commands off until an owner turns them on with `[p]slash enable` and `[p]slash sync`.

### Archiver (`archiver`)
- **`archiver enable`**: Turn on video archiving in this server
- **`archiver disable`**: Turn it off
- **`archiver queue`**: Show the processing queue
- **`archiver status`**: Show cog, queue, processor and health status

### Settings (`settings`)
- **`settings`**: Show the current settings
- **`settings setchannel <channel>`**: Set the archive channel
- **`settings setlog <channel>`**: Set the log channel
- **`settings addchannel <channel>`**: Add a channel to monitor
- **`settings removechannel <channel>`**: Stop monitoring a channel
- **`settings setformat <mp4|webm|mkv>`**: Set the video format
- **`settings setquality <144-4320>`**: Set the max video height in pixels
- **`settings setmaxsize <1-100>`**: Set the max file size in MB
- **`settings setmessageduration <0-168>`**: How long archive messages stay, in hours (0 keeps them)
- **`settings settemplate <template>`**: Set the archive message template. Placeholders: `{author}`, `{channel}`, `{original_message}`
- **`settings setconcurrent <1-5>`**: Set how many downloads run at once

### Database (`archivedb`)
- **`archivedb enable`**: Turn on the archive database
- **`archivedb disable`**: Turn it off
- **`archivedb check <url>`**: Check whether a URL was already archived
- **`archivedb status`**: Show database status and stats

## yt-dlp updates

The cog upgrades yt-dlp when it starts and then once a day, with `pip install --upgrade yt-dlp` in the bot's environment. A new version gets swapped in without restarting the bot. Downloads already running finish on the old one. Updates show up in the bot log.

## Default Settings

```python
{
    "enabled": True,               # Video archiving enabled by default
    "archive_channel": None,       # Must be set before use
    "log_channel": None,          # Optional error logging channel
    "enabled_channels": [],       # Empty list means all channels
    "allowed_roles": [],         # Empty list means all roles
    "video_format": "mp4",      # Default video format
    "video_quality": "high",    # Default video quality
    "max_file_size": 8,        # Maximum file size in MB
    "message_duration": 30,    # Message duration in hours
    "message_template": "{author} archived a video from {channel}",
    "concurrent_downloads": 2, # Number of concurrent downloads
    "enabled_sites": None,    # None means all sites enabled
    "use_database": False    # Database tracking disabled by default
}
```

## Message Templates

You can customize archive messages using these variables:
- `{author}`: Original message author
- `{url}`: Original video URL
- `{original_message}`: Link to original message
- `{channel}`: Original channel name

Example template:
```
📥 Video archived from {author}
Original: {url}
Source: {original_message}
Channel: {channel}
```

## Site Support

The cog supports every site yt-dlp supports.

## Performance & Limitations

- Hardware acceleration automatically detected and utilized
- Configurable concurrent downloads (1-5)
- Maximum queue size: 1000 items
- Maximum file size: 8MB by default (configurable up to Discord's limit)
- Maximum video quality: 4320p (8K)
- Automatic retry on failures (3 attempts with 5-second delay)
- Queue cleanup interval: 30 minutes
- Maximum history age: 24 hours
- Unload timeout: 30 seconds
- Cleanup timeout: 15 seconds
- Queue state persistence across restarts

## Error Handling

- Comprehensive error logging
- Dedicated log channel for issues
- Automatic retry mechanism
- Queue persistence across restarts
- Detailed error messages
- Error type tracking and analysis
- Automatic recovery procedures
- Force cleanup on timeout
- Enhanced error reporting

## Support

If you encounter any issues or have questions, please open an issue on the [GitHub repository](https://github.com/pacnpal/Pac-cogs).
