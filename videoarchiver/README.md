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

All commands support both prefix (`[p]videoarchiver` or `[p]va`) and slash command (`/videoarchiver`) syntax:

### Core Settings
- **`setchannel <channel>`**: Set the archive channel
- **`setnotification <channel>`**: Set the notification channel
- **`setlogchannel <channel>`**: Set the log channel for errors
- **`setformat <mp4|webm>`**: Set video format
- **`setquality <144-4320>`**: Set maximum video quality (in pixels)
- **`setmaxsize <1-100>`**: Set maximum file size (in MB)
- **`setconcurrent <1-5>`**: Set number of concurrent downloads

### Channel Monitoring
- **`addmonitor [channel]`**: Add channel to monitor (empty for all channels)
- **`removemonitor <channel>`**: Remove channel from monitoring
- **`toggledelete`**: Toggle deletion of local files after reposting

### Message Configuration
- **`setduration <0-720>`**: Set message duration in hours (0 for permanent)
- **`settemplate <template>`**: Set message template using {author}, {url}, {original_message}

### Role Management
- **`addrole [role]`**: Add allowed role (empty for @everyone)
- **`removerole <role>`**: Remove allowed role
- **`listroles`**: List allowed roles

### Site Management
- **`enablesites [sites...]`**: Enable specific sites (empty for all)
- **`listsites`**: List available and enabled sites

### Queue Management
- **`queue`**: Show current queue status with basic metrics
- **`queuemetrics`**: Show detailed queue performance metrics
- **`clearqueue`**: Clear the video processing queue

### System Management
- **`updateytdlp`**: Update yt-dlp to latest version
- **`toggleupdates`**: Toggle update notifications

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

The cog supports all sites compatible with yt-dlp. Use `[p]va listsites` to see available sites and currently enabled ones.

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
