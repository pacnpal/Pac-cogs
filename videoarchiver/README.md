# VideoArchiver Cog

A Red-DiscordBot cog for automatically archiving videos from monitored Discord channels.

## Features

- Automatically detects and downloads videos from monitored channels
- Supports multiple video hosting platforms through yt-dlp
- Enhanced queue system with priority processing and performance metrics
- Configurable video quality and format
- Role-based access control
- Automatic file cleanup
- Hardware-accelerated video processing (when available)
- Customizable notification messages
- Queue persistence across bot restarts

## File Structure

The cog is organized into several modules for better maintainability:

- `video_archiver.py`: Main cog class and entry point
- `commands.py`: Discord command handlers
- `config_manager.py`: Guild configuration management
- `processor.py`: Video processing logic
- `enhanced_queue.py`: Advanced queue management system
- `update_checker.py`: yt-dlp update management
- `utils.py`: Utility functions and classes
- `ffmpeg_manager.py`: FFmpeg configuration and hardware acceleration
- `exceptions.py`: Custom exception classes

## Installation

1. Install the cog using Red's cog manager:
```bash
[p]repo add videoarchiver <repository_url>
[p]cog install videoarchiver
```

2. Load the cog:
```bash
[p]load videoarchiver
```

## Configuration

Use the following commands to configure the cog:

### Channel Settings
- `[p]va setchannel <channel>`: Set the archive channel
- `[p]va setnotification <channel>`: Set the notification channel
- `[p]va setlogchannel <channel>`: Set the log channel
- `[p]va addmonitor <channel>`: Add a channel to monitor
- `[p]va removemonitor <channel>`: Remove a monitored channel

### Role Management
- `[p]va addrole <role>`: Add a role allowed to trigger archiving
- `[p]va removerole <role>`: Remove an allowed role
- `[p]va listroles`: List allowed roles

### Video Settings
- `[p]va setformat <format>`: Set video format (e.g., mp4, webm)
- `[p]va setquality <pixels>`: Set maximum video quality (e.g., 1080)
- `[p]va setmaxsize <MB>`: Set maximum file size in MB
- `[p]va setconcurrent <count>`: Set number of concurrent downloads (1-5)

### Message Settings
- `[p]va setduration <hours>`: Set how long to keep archive messages
- `[p]va settemplate <template>`: Set archive message template
- `[p]va toggledelete`: Toggle deletion of local files after reposting

### Site Management
- `[p]va enablesites [sites...]`: Enable specific sites (empty for all)
- `[p]va listsites`: List available and enabled sites

### Queue Management
- `[p]va queue`: Show detailed queue status and metrics
- `[p]va clearqueue`: Clear the processing queue
- `[p]va queuemetrics`: Display queue performance metrics

### Update Management
- `[p]va updateytdlp`: Update yt-dlp to latest version
- `[p]va toggleupdates`: Toggle update notifications

## Technical Details

### Enhanced Queue System
The cog uses an advanced queue system with the following features:
- Priority-based processing (first URL in messages gets highest priority)
- Queue persistence across bot restarts
- Automatic memory management and cleanup
- Performance metrics tracking (success rate, processing times)
- Health monitoring with automatic issue detection
- Deadlock prevention
- Configurable cleanup intervals
- Size-limited queue to prevent memory issues
- Detailed status tracking per guild

### Queue Metrics
The queue system tracks various performance metrics:
- Total processed videos
- Success/failure rates
- Average processing time
- Peak memory usage
- Queue size per guild/channel
- Processing history
- Cleanup statistics

### Configuration Management
- Settings are stored per guild
- Supports hot-reloading of configurations
- Automatic validation of settings

### Error Handling
- Comprehensive error logging
- Automatic retry mechanisms with configurable attempts
- Guild-specific error reporting
- Detailed failure tracking

### Performance Optimizations
- Hardware-accelerated video processing when available
- Efficient file handling with secure deletion
- Memory leak prevention through proper resource cleanup
- Automatic resource monitoring
- Periodic cleanup of old queue items
- Memory usage optimization

## Requirements

- Python 3.8 or higher
- FFmpeg
- yt-dlp
- Discord.py 2.0 or higher
- Red-DiscordBot V3
- psutil>=5.9.0

## Support

For issues and feature requests, please use the issue tracker on GitHub.
