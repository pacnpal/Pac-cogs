# VideoArchiver Cog for Red-DiscordBot

A powerful video archiving cog that automatically downloads and reposts videos from monitored channels. Features hardware-accelerated compression, multi-video processing, and support for multiple video platforms.

## Features

- **Automatic Video Processing**
  - Monitors specified channels for videos
  - Supports multiple video platforms through yt-dlp
  - Hardware-accelerated compression (NVIDIA, AMD, Intel, ARM)
  - Configurable video quality and format
  - Automatic file size optimization for Discord limits

- **Enhanced Queue System**
  - Priority-based processing
  - Queue persistence across bot restarts
  - Performance metrics tracking
  - Automatic cleanup and memory management
  - Real-time queue status monitoring
  - Detailed performance analytics

- **Channel Management**
  - Flexible channel monitoring (specific channels or all)
  - Separate archive, notification, and log channels
  - Customizable message templates
  - Configurable message duration

- **Access Control**
  - Role-based permissions
  - Site-specific enabling/disabling
  - Admin-only configuration commands

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
- **`va_format <mp4|webm>`**: Set video format
- **`va_quality <144-4320>`**: Set maximum video quality (in pixels)
- **`va_maxsize <1-100>`**: Set maximum file size (in MB)
- **`va_concurrent <1-5>`**: Set number of concurrent downloads
- **`va_toggledelete`**: Toggle deletion of local files after reposting
- **`va_duration <0-720>`**: Set message duration in hours (0 for permanent)
- **`va_template <template>`**: Set message template using {author}, {url}, {original_message}
- **`va_update`**: Update yt-dlp to latest version
- **`va_toggleupdates`**: Toggle update notifications

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

## Queue System

The enhanced queue system provides:

### Basic Metrics
- Pending/Processing/Completed/Failed counts
- Success rate percentage
- Average processing time

### Detailed Metrics
- Total processed videos
- Total failures
- Peak memory usage
- Last cleanup time
- Real-time queue state

## Message Templates

You can customize archive messages using these variables:
- `{author}`: Original message author
- `{url}`: Original video URL
- `{original_message}`: Link to original message

Example template:
```
📥 Video archived from {author}
Original: {url}
Source: {original_message}
```

## Site Support

The cog supports all sites compatible with yt-dlp. Use `vas_list` to see available sites and currently enabled ones.

## Performance

- Hardware acceleration automatically detected and utilized
- Configurable concurrent downloads (1-5)
- Automatic file size optimization
- Memory-efficient queue management
- Automatic cleanup of temporary files

## Error Handling

- Comprehensive error logging
- Dedicated log channel for issues
- Automatic retry mechanism
- Queue persistence across restarts
- Detailed error messages

## Support

If you encounter any issues or have questions, please open an issue on the [GitHub repository](https://github.com/pacnpal/Pac-cogs).
