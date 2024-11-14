# VideoArchiver Cog for Red-DiscordBot

A powerful video archiving cog that automatically downloads and reposts videos from monitored channels, with support for GPU-accelerated compression, multi-video processing, and role-based permissions.

## Features

- **Hardware-Accelerated Video Processing**:
  - NVIDIA GPU support using NVENC
  - AMD GPU support using AMF
  - Intel GPU support using QuickSync
  - ARM64/aarch64 support with V4L2 M2M encoder
  - Multi-core CPU optimization
- **Smart Video Processing**:
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

## Quick Installation

1. Install the cog:
```
[p]repo add video-archiver https://github.com/yourusername/discord-video-bot
[p]cog install video-archiver video_archiver
[p]load video_archiver
```

The required dependencies will be installed automatically. If you need to install them manually:
```bash
python -m pip install -U yt-dlp>=2024.11.4 ffmpeg-python>=0.2.0 requests>=2.32.3
```

### Important: Keeping yt-dlp Updated

The cog relies on [yt-dlp](https://github.com/yt-dlp/yt-dlp) for video downloading. Video platforms frequently update their sites, which may break video downloading if yt-dlp is outdated. To ensure continued functionality, regularly update yt-dlp:

```bash
[p]pipinstall --upgrade yt-dlp

# Or manually:
python -m pip install -U yt-dlp
```

**Note**: Before submitting any GitHub issues related to video downloading, please ensure you have updated yt-dlp to the latest version first, as most downloading issues can be resolved by updating.

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

## Architecture Support

The cog supports multiple architectures:
- x86_64/amd64
- ARM64/aarch64
- ARMv7 (32-bit)
- Apple Silicon (M1/M2)

Hardware acceleration is automatically configured based on your system:
- x86_64: Full GPU support (NVIDIA, AMD, Intel)
- ARM64: V4L2 M2M hardware encoding when available
- All platforms: Multi-core CPU optimization

## Troubleshooting

1. **Permission Issues**:
   - Bot needs "Manage Messages" permission
   - Bot needs "Attach Files" permission
   - Bot needs "Read Message History" permission
   - Bot needs "Use Application Commands" for slash commands

2. **Video Processing Issues**:
   - Ensure FFmpeg is properly installed
   - Check GPU drivers are up to date
   - Verify file permissions in the downloads directory
   - Update yt-dlp if videos fail to download

3. **Role Issues**:
   - Verify role hierarchy (bot's role must be higher than managed roles)
   - Check if roles are properly configured

4. **Performance Issues**:
   - Check available disk space
   - Monitor system resource usage

## Support

For support:
1. First, check the [Troubleshooting](#troubleshooting) section above
2. Update yt-dlp to the latest version:
   ```bash
   [p]pipinstall --upgrade yt-dlp
   # Or manually:
   python -m pip install -U yt-dlp
   ```
3. If the issue persists after updating yt-dlp:
   - Join the Red-DiscordBot server and ask in the #support channel
   - Open an issue on GitHub with:
     - Your Red-Bot version
     - The output of `[p]pipinstall list`
     - Steps to reproduce the issue
     - Any error messages

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

Before submitting an issue:
1. Update yt-dlp to the latest version first:
   ```bash
   [p]pipinstall --upgrade yt-dlp
   # Or manually:
   python -m pip install -U yt-dlp
   ```
2. If the issue persists after updating yt-dlp, please include:
   - Your Red-Bot version
   - The output of `[p]pipinstall list`
   - Steps to reproduce the issue
   - Any error messages

## License

This cog is licensed under the MIT License - see the [LICENSE](../LICENSE) file for details.
