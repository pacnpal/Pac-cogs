# VideoArchiver Cog

A Red-DiscordBot cog for automatically archiving videos from monitored Discord channels. Supports both traditional prefix commands and Discord slash commands.

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
- Full slash command support for all commands

## File Structure

The cog is organized into several modules for better maintainability:

### Core Files
- `video_archiver.py`: Main cog class and entry point
- `commands.py`: Discord command handlers
- `config_manager.py`: Guild configuration management
- `processor.py`: Video processing logic
- `enhanced_queue.py`: Advanced queue management system
- `update_checker.py`: yt-dlp update management
- `exceptions.py`: Custom exception classes

### Utils Package
- `utils/video_downloader.py`: Video download and processing
- `utils/message_manager.py`: Message handling and cleanup
- `utils/file_ops.py`: File operations and secure deletion
- `utils/path_manager.py`: Path management utilities
- `utils/exceptions.py`: Utility-specific exceptions

### FFmpeg Package
- `ffmpeg/ffmpeg_manager.py`: FFmpeg configuration and management
- `ffmpeg/gpu_detector.py`: GPU capability detection
- `ffmpeg/video_analyzer.py`: Video analysis utilities
- `ffmpeg/encoder_params.py`: Encoding parameter optimization
- `ffmpeg/ffmpeg_downloader.py`: FFmpeg binary management
- `ffmpeg/exceptions.py`: FFmpeg-specific exceptions

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

Use the following commands to configure the cog. All commands support both prefix and slash command syntax:

### Channel Settings
- Set the archive channel:
  ```
  [p]va setchannel <channel>
  ```
  or
  ```
  /va setchannel <channel>
  ```

- Set the notification channel:
  ```
  [p]va setnotification <channel>
  ```
  or
  ```
  /va setnotification <channel>
  ```

- Set the log channel:
  ```
  [p]va setlogchannel <channel>
  ```
  or
  ```
  /va setlogchannel <channel>
  ```

- Add/remove a monitored channel:
  ```
  [p]va addmonitor <channel>
  [p]va removemonitor <channel>
  ```
  or
  ```
  /va addmonitor <channel>
  /va removemonitor <channel>
  ```

### Role Management
- Add/remove allowed roles:
  ```
  [p]va addrole <role>
  [p]va removerole <role>
  [p]va listroles
  ```
  or
  ```
  /va addrole <role>
  /va removerole <role>
  /va listroles
  ```

### Video Settings
- Set video format and quality:
  ```
  [p]va setformat <format>
  [p]va setquality <pixels>
  [p]va setmaxsize <MB>
  [p]va setconcurrent <count>
  ```
  or
  ```
  /va setformat <format>
  /va setquality <pixels>
  /va setmaxsize <MB>
  /va setconcurrent <count>
  ```

### Message Settings
- Configure message handling:
  ```
  [p]va setduration <hours>
  [p]va settemplate <template>
  [p]va toggledelete
  ```
  or
  ```
  /va setduration <hours>
  /va settemplate <template>
  /va toggledelete
  ```

### Site Management
- Manage supported sites:
  ```
  [p]va enablesites [sites...]
  [p]va listsites
  ```
  or
  ```
  /va enablesites [sites...]
  /va listsites
  ```

### Queue Management
- Manage the processing queue:
  ```
  [p]va queue
  [p]va clearqueue
  [p]va queuemetrics
  ```
  or
  ```
  /va queue
  /va clearqueue
  /va queuemetrics
  ```

### Update Management
- Manage yt-dlp updates:
  ```
  [p]va updateytdlp
  [p]va toggleupdates
  ```
  or
  ```
  /va updateytdlp
  /va toggleupdates
  ```

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
