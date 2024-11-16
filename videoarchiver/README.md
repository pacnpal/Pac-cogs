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

All commands support both prefix and slash command syntax:

### Core Video Archiver Commands (va_)
- **`va_settings`**: Show current video archiver settings
- **`va_format <mp4|webm|mkv>`**: Set video format
- **`va_quality <144-4320>`**: Set maximum video quality (in pixels)
- **`va_maxsize <1-100>`**: Set maximum file size (in MB)
- **`va_concurrent <1-5>`**: Set number of concurrent downloads
- **`va_toggledelete`**: Toggle deletion of local files after reposting
- **`va_duration <0-168>`**: Set message duration in hours (0 for permanent)
- **`va_template <template>`**: Set message template using {author}, {url}, {original_message}
- **`va_update`**: Update yt-dlp to latest version
- **`va_toggleupdates`**: Toggle update notifications

### Database Management Commands (archivedb_)
- **`archivedb enable`**: Enable the video archive database
- **`archivedb disable`**: Disable the video archive database
- **`checkarchived <url>`**: Check if a video URL has been archived

### Archiver Management Commands (archiver_)
- **`archiver enable`**: Enable video archiving in the server
- **`archiver disable`**: Disable video archiving in the server
- **`archiver setchannel <channel>`**: Set the archive channel
- **`archiver setlog <channel>`**: Set the log channel
- **`archiver addchannel <channel>`**: Add a channel to monitor
- **`archiver removechannel <channel>`**: Remove a channel from monitoring
- **`archiver queue`**: Show current queue status

### Queue Management Commands (vaq_)
- **`vaq_status`**: Show current queue status with basic metrics
- **`vaq_metrics`**: Show detailed queue performance metrics
- **`vaq_clear`**: Clear the video processing queue

### Channel Configuration Commands (vac_)
- **`vac_archive <channel>`**: Set the archive channel
- **`vac_notify <channel>`**: Set the notification channel
- **`vac_log <channel>`**: Set the log channel for errors
- **`vac_monitor [channel]`**: Add channel to monitor (empty for all channels)
- **`vac_unmonitor <channel>`**: Remove channel from monitoring

### Role Management Commands (var_)
- **`var_add [role]`**: Add allowed role (empty for @everyone)
- **`var_remove <role>`**: Remove allowed role
- **`var_list`**: List allowed roles

### Site Management Commands (vas_)
- **`vas_enable [sites...]`**: Enable specific sites (empty for all)
- **`vas_list`**: List available and enabled sites

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

The cog supports all sites compatible with yt-dlp. Use `vas_list` to see available sites and currently enabled ones.

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
