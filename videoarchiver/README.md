# VideoArchiver Cog for Red-DiscordBot

A powerful video archiving cog that automatically downloads and reposts videos from monitored channels, with support for GPU-accelerated compression, multi-video processing, and role-based permissions.

## Features

- **Hardware-Accelerated Video Processing**:
  - NVIDIA GPU support using NVENC with advanced encoding options
  - AMD GPU support using AMF with quality preservation
  - Intel GPU support using QuickSync with look-ahead
  - ARM64/aarch64 support with V4L2 M2M encoder
  - Multi-core CPU optimization with advanced parameters
  - Automatic GPU fallback to CPU if hardware encoding fails
- **Smart Video Processing**:
  - Content-aware video analysis
  - Dark scene detection and optimization
  - Motion detection and adaptation
  - Dynamic audio bitrate allocation
  - Intelligent quality preservation
  - Only compresses when needed
  - Concurrent video processing
  - Default 8MB file size limit
- **Role-Based Access**:
  - Restrict archiving to specific roles
  - Default allows all users
  - Per-guild role configuration
- **Wide Platform Support**:
  - Support for multiple video platforms via [yt-dlp](https://github.com/yt-dlp/yt-dlp)
  - Configurable site whitelist
  - Automatic quality selection
- **Automatic Updates**:
  - Automatic yt-dlp update checking
  - Semantic version comparison
  - Bot owner notifications for new versions
  - Easy update command
  - Configurable update notifications
  - Retries for update operations
- **Error Handling & Logging**:
  - Detailed error logging to Discord channels
  - Full error tracebacks for debugging
  - Automatic retries for Discord operations
  - Proper resource cleanup
  - Task tracking and management

## Installation

To install this cog, follow these steps:

1. Ensure you have Red-DiscordBot V3 installed.
2. Add the repository to your bot:

   ```
   [p]repo add Pac-cogs https://github.com/pacnpal/Pac-cogs
   ```

3. Install the VideoArchiver cog:

   ```
   [p]cog install Pac-cogs videoarchiver
   ```

4. Load the cog:

   ```
   [p]load videoarchiver
   ```

Replace `[p]` with your bot's prefix.

The required dependencies (yt-dlp, ffmpeg-python, requests, aiohttp) will be installed automatically. You will also need FFmpeg installed on your system - the cog will attempt to download and manage FFmpeg automatically if it's not found.

### Important: Keeping yt-dlp Updated

The cog relies on [yt-dlp](https://github.com/yt-dlp/yt-dlp) for video downloading. Video platforms frequently update their sites, which may break video downloading if yt-dlp is outdated. The cog will automatically check for updates and notify the bot owner when a new version is available.

To update yt-dlp:
```bash
[p]videoarchiver updateytdlp
```

You can also disable update notifications per guild:
```bash
[p]videoarchiver toggleupdates
```

## Configuration

The cog supports both slash commands and traditional prefix commands. Use whichever style you prefer.

### Channel Setup
```
/videoarchiver setchannel #archive-channel     # Set archive channel
/videoarchiver setnotification #notify-channel # Set notification channel
/videoarchiver setlogchannel #log-channel     # Set log channel for errors/notifications
/videoarchiver addmonitor #videos-channel      # Add channel to monitor
/videoarchiver removemonitor #channel         # Remove monitored channel

# Legacy commands also supported:
[p]videoarchiver setchannel #channel
[p]videoarchiver setnotification #channel
etc.
```

### Role Management
```
/videoarchiver addrole @role      # Add role that can trigger archiving
/videoarchiver removerole @role   # Remove role from allowed list
/videoarchiver listroles          # List all allowed roles (empty = all allowed)
```

### Video Settings
```
/videoarchiver setformat mp4    # Set video format
/videoarchiver setquality 1080  # Set max quality (pixels)
/videoarchiver setmaxsize 8     # Set max size (MB, default 8MB)
/videoarchiver toggledelete     # Toggle file cleanup
```

### Message Settings
```
/videoarchiver setduration 24   # Set message duration (hours)
/videoarchiver settemplate "Archived video from {author}\nOriginal: {original_message}"
/videoarchiver enablesites      # Configure allowed sites
```

### Update Settings
```
/videoarchiver updateytdlp      # Update yt-dlp to latest version
/videoarchiver toggleupdates    # Toggle update notifications
```

## Architecture Support

The cog supports multiple architectures with intelligent hardware detection:
- x86_64/amd64: Full GPU support with automatic encoder testing
- ARM64/aarch64: Hardware encoding with automatic capability detection
- ARMv7 (32-bit): Optimized CPU encoding
- Apple Silicon (M1/M2): Native ARM support

Hardware acceleration features:
- Automatic GPU detection and testing
- Fallback to CPU if GPU encoding fails
- Dynamic encoder parameter optimization
- Multi-pass encoding for better quality
- Content-aware encoding settings

## Error Handling

The cog includes comprehensive error handling:

1. **Discord API Operations**:
   - Automatic retries for failed operations
   - Configurable retry attempts and delays
   - Proper error logging to Discord channels

2. **Video Processing**:
   - Automatic GPU fallback if hardware encoding fails
   - Temporary file cleanup on errors
   - Resource leak prevention
   - Task cancellation handling

3. **Update Management**:
   - Proper version comparison
   - Network timeout handling
   - Update notification retries
   - Error context preservation

4. **Resource Management**:
   - Proper task tracking and cleanup
   - Component lifecycle management
   - File handle cleanup
   - Memory leak prevention

## Troubleshooting

1. **Permission Issues**:
   - Bot needs "Manage Messages" permission
   - Bot needs "Attach Files" permission
   - Bot needs "Read Message History" permission
   - Bot needs "Use Application Commands" for slash commands

2. **Video Processing Issues**:
   - Check log channel for detailed error messages
   - Ensure FFmpeg is properly installed
   - Check GPU drivers are up to date
   - Verify file permissions in the downloads directory
   - Update yt-dlp if videos fail to download

3. **Role Issues**:
   - Verify role hierarchy (bot's role must be higher than managed roles)
   - Check if roles are properly configured
   - Check log channel for permission errors

4. **Performance Issues**:
   - Check available disk space
   - Monitor system resource usage
   - Check log channel for encoding errors
   - Verify GPU availability and status

## Support

For support:
1. First, check the [Troubleshooting](#troubleshooting) section above
2. Check the log channel for detailed error messages
3. Update yt-dlp to the latest version:
   ```bash
   [p]videoarchiver updateytdlp
   ```
4. If the issue persists after updating yt-dlp:
   - Join the Red-DiscordBot server and ask in the #support channel
   - Open an issue on GitHub with:
     - Your Red-Bot version
     - The output of `[p]pipinstall list`
     - Steps to reproduce the issue
     - Any error messages from the log channel
     - Your hardware configuration (CPU/GPU)

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

Before submitting an issue:
1. Update yt-dlp to the latest version first:
   ```bash
   [p]videoarchiver updateytdlp
   ```
2. If the issue persists after updating yt-dlp, please include:
   - Your Red-Bot version
   - The output of `[p]pipinstall list`
   - Steps to reproduce the issue
   - Any error messages from the log channel
   - Your hardware configuration (CPU/GPU)
   - FFmpeg version and configuration

## License

This cog is licensed under the MIT License - see the [LICENSE](../LICENSE) file for details.
