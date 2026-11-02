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
  - Default video quality: 1080p
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
  - Videos are processed one at a time
  - Maximum queue size: 1000 items
  - Automatic retry on failures (3 attempts with 5-second delay)
  - Queue state persistence across bot restarts. Videos that were mid-download when the bot stopped go back in the queue

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
  - Separate archive and log channels
  - Customizable message templates
  - Configurable message duration (0-168 hours)

- **Access Control**
  - Role-based permissions
  - Admin-only configuration commands
  - Per-guild settings

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

3. Set it up in each server. Archiving is off until you turn it on:
```bash
[p]settings setchannel #archive
[p]archiver enable
```

## Commands

Every command works as a prefix command and as a slash command. Red keeps slash commands off until an owner turns them on with `[p]slash enablecog videoarchiver` and then `[p]slash sync`.

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
- **`settings settemplate <template>`**: Set the archive message template. It must include `{username}` and `{channel}`, and can also use `{author}`, `{url}` and `{original_message}`
- **`settings setconcurrent <1-5>`**: Set how many downloads run at once. For now the queue still processes one video at a time, so this has no effect yet

Settings changes take effect right away. A download that's already running finishes with the old settings.

### Database (`archivedb`)
- **`archivedb enable`**: Turn on the archive database
- **`archivedb disable`**: Turn it off
- **`archivedb check <url>`**: Check whether a URL was already archived
- **`archivedb status`**: Show database status and this server's stats

The database is shared by every server the bot is in. It stays open while any server has it on. With it on, a link this server already archived gets a reply pointing at the earlier archive instead of being downloaded again, and reacting 🔄 to a message looks up its links.

## yt-dlp updates

The cog upgrades yt-dlp when it starts and then once a day, with `pip install --upgrade yt-dlp` in the bot's environment. A new version gets swapped in without restarting the bot. Downloads already running finish on the old one. Updates show up in the bot log.

## Default Settings

```python
{
    "enabled": False,              # Turn on with archiver enable
    "archive_channel": None,       # Must be set before use
    "log_channel": None,           # Optional error logging channel
    "monitored_channels": [],      # Empty list means all channels
    "allowed_roles": [],           # Empty list means everyone
    "video_format": "mp4",
    "video_quality": 1080,         # Max height in pixels
    "max_file_size": 8,            # MB
    "message_duration": 24,        # Hours before the archive message is deleted (0 keeps it)
    "message_template": "Video from {username} in #{channel}\nOriginal: {original_message}",
    "concurrent_downloads": 3,     # No effect yet, see setconcurrent
    "use_database": False
}
```

## Message Templates

You can customize archive messages using these variables. `{username}` and `{channel}` are required:
- `{username}`: Original message author's name
- `{author}`: Original message author (mention)
- `{url}`: Original video URL
- `{original_message}`: Link to original message
- `{channel}`: Original channel name

Example template:
```
📥 Video archived from {username}
Original: {url}
Source: {original_message}
Channel: {channel}
```

## Site Support

The cog picks up links to any site yt-dlp supports (its [supported sites list](https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md)), plus direct links to video files. The list comes from the installed yt-dlp, so updating yt-dlp adds sites with no cog change. Links yt-dlp treats as playlist-only are skipped; anything else that turns out to hold several videos (a multi-video tweet, a YouTube channel or playlist) archives just the first one. Links in `<...>` or spoiler tags still count.

`enabled_sites` takes yt-dlp site names (`youtube`, `twitter`, `tiktok`, ...) or domain fragments (`vimeo.com`); empty means every site.

## Performance & Limitations

- Hardware acceleration automatically detected and utilized
- One video is processed at a time
- Maximum queue size: 1000 items
- Maximum file size: 8MB by default (configurable up to Discord's limit)
- Maximum video quality: 4320p (8K)
- Automatic retry on failures (3 attempts with 5-second delay)
- Queue cleanup interval: 1 hour
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
