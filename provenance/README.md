# Provenance Cog for Red-DiscordBot

This cog checks images (and optionally audio) for OpenAI provenance signals using OpenAI's [Content Provenance API](https://developers.openai.com/api/docs/guides/content-provenance). It looks for two separate things: C2PA Content Credentials, which is signed metadata, and a SynthID watermark, which is embedded in the pixels or audio itself. You can check files by hand, auto scan attachments in chosen channels, and scan member avatars into a private log channel. Supports both traditional prefix commands and slash commands.

## What it detects (and what it doesn't)

This cog only detects **OpenAI's** signals. It doesn't detect images from Google, Midjourney, Stable Diffusion, or any other company, even if they carry their own watermark or Content Credentials.

- A detection means "OpenAI SynthID watermark detected" or "OpenAI Content Credentials detected." It's evidence of that specific signal, not a full history of the file.
- Finding nothing doesn't prove a person made the file. Metadata gets stripped when files are edited, converted, screenshotted, or re-uploaded. Watermarks can degrade. Older OpenAI models didn't add these signals at all.
- The cog never says a file "is AI" or "is not AI." It reports which OpenAI signals were found.
- C2PA results are shown with their issuer and validation state. An `invalid` manifest isn't reliable evidence and is labeled that way.
- Audio only gets a SynthID check. There's no C2PA for audio.

## Installation

To install this cog, follow these steps:

1. Ensure you have Red-DiscordBot 3.5 or later installed.
2. Add the repository to your bot:

   ```
   [p]repo add Pac-cogs https://github.com/pacnpal/Pac-cogs
   ```

3. Install the Provenance cog:

   ```
   [p]cog install Pac-cogs provenance
   ```

4. Load the cog:

   ```
   [p]load provenance
   ```

5. (Optional) Enable the slash commands:

   ```
   [p]slash enablecog provenance
   [p]slash sync
   ```

Replace `[p]` with your bot's prefix.

## Setup

1. Set your OpenAI API key with Red's shared API tokens. The key is never stored in the cog's own config.

   ```
   [p]set api openai api_key,sk-your-key-here
   ```

   The key's organization needs access to the Content Provenance API. If OpenAI rejects the key or says it doesn't have access, the bot owner gets one DM and all checks, manual and automatic, stop until the `openai` token is changed.

2. Turn on the intents the cog needs in the [Discord Developer Portal](https://discord.com/developers/applications) under your bot's **Bot** page:
   - **Message Content Intent** is needed for auto scan and for prefix commands with attachments.
   - **Server Members Intent** is needed for avatar scanning. Without it the bot never sees joins or avatar changes.

   Red requests these intents on startup, so restart the bot after turning them on.

3. (Optional) Turn on auto scanning for a channel:

   ```
   [p]provenanceset addchannel #art
   [p]provenanceset autoscan true
   ```
   or
   ```
   /provenanceset addchannel #art
   /provenanceset autoscan true
   ```

4. (Optional) Turn on avatar scanning. Set a private log channel first, since avatar results are only ever posted there:

   ```
   [p]provenanceset setlog #mod-log
   [p]provenanceset avatarscan true
   ```

## Usage

### Checking a file

Use `[p]provenance` or `/provenance` in any of these ways:

- Attach one or more images or audio files to the command (up to 10 are checked). The slash command takes one file.
- Reply to a message that has attachments and run `[p]provenance` with nothing else.
- Give a link: `[p]provenance https://example.com/image.png`

Each file gets an embed with the C2PA and SynthID results shown separately, plus the C2PA issuer, model, and generation time when OpenAI returns them. If nothing is found, it says no OpenAI signal was found and that this doesn't prove a person made it.

Links are downloaded by the bot. It refuses URLs that resolve to private, loopback, or link-local addresses, follows at most 3 redirects, and stops at 50 MiB.

### Auto scan

When auto scan is on, the bot checks every supported image attachment in the configured channels. Bots are ignored.

- If a SynthID watermark is detected, the bot replies to the message saying so.
- If only C2PA Content Credentials are detected, the bot stays quiet unless `c2pareplies` is on.
- If nothing is detected, the bot says nothing.
- Audio attachments (including voice messages) are only checked when `audioscan` is on.

Channel mode decides how the channel list is used. In `allow` mode (the default) only listed channels are scanned, so an empty list scans nothing. In `deny` mode every channel except the listed ones is scanned. Threads and forum posts follow their parent channel.

### Avatar scan

When avatar scan is on and a log channel is set:

- A member's avatar is checked when they join.
- When someone changes their global avatar, it's checked once and the result goes to every server they share with the bot that has avatar scanning on.
- When someone changes their server avatar, it's checked for that server only.
- Default avatars are skipped. Avatars are fetched at the largest size in their native format (PNG, or GIF if animated).

Detections are posted only to the log channel as an embed with the user's mention, ID, avatar thumbnail, and results. Avatar results are never posted publicly. Discord re-encodes avatars on upload, so C2PA metadata is usually gone by then. SynthID has a better chance of surviving.

## Commands

All commands support both prefix and slash command syntax.

### User Commands
- `[p]provenance [file] [url]` or `/provenance`: Check an attachment, a replied-to message's attachments, or a URL. Has a 10 second per-user cooldown.

### Admin Commands
All settings commands need the admin role or the Administrator permission.

- `[p]provenanceset` or `/provenanceset show`: Show the current settings
- `[p]provenanceset autoscan <true|false>`: Turn auto scanning on or off (off by default)
- `[p]provenanceset channelmode <allow|deny>`: Use the channel list as an allowlist or a denylist
- `[p]provenanceset addchannel <channel>`: Add a channel to the list
- `[p]provenanceset removechannel <channel>`: Remove a channel from the list
- `[p]provenanceset c2pareplies <true|false>`: Also reply when only C2PA Content Credentials are found (off by default)
- `[p]provenanceset audioscan <true|false>`: Include audio attachments in auto scan (off by default)
- `[p]provenanceset avatarscan <true|false>`: Scan avatars on join and on change (off by default)
- `[p]provenanceset setlog [channel]`: Set the private log channel for avatar results. Leave the channel out to clear it.

## Limits and costs

- Supported formats come from OpenAI's docs. Images: PNG, JPEG, WebP, GIF. Audio: MP3, Opus/Ogg, AAC, FLAC, WAV, PCM. The file extension and the reported MIME type both have to match a supported format before anything is uploaded. Files over 50 MiB are skipped, and OpenAI rejects audio longer than 60 seconds.
- Results are cached in memory by the SHA-256 of the file for 6 hours (up to 1024 files), so reposting the same file doesn't call the API again.
- At most 2 API calls run at once across the whole bot. Auto scans, join scans, and server avatar scans are limited to 10 API calls per server per minute. Anything past that is skipped quietly. Auto scan holds at most 4 files in memory at once, and no more than 2 of those can come from one server. Avatar scans share those same slots. Attachments and avatars that arrive while their slots are full, or after their server has hit its limit, are skipped without downloading, so a flood of uploads or a join raid can't pile up downloads or crowd out other servers.
- Rate limits (429), server errors, timeouts and connection errors are tried up to 4 times in total, with backoff and jitter. A rejected file (400) is logged and skipped. Errors from auto scans only go to the bot's log, never to channels.

## Data

The cog stores per-server settings only: toggles and channel IDs. Files and avatars it checks are sent to OpenAI. The result cache lives in memory and is cleared when the cog unloads. No user data is stored, so there's nothing for Red's data deletion to remove.

## Support

If you encounter any issues or have questions, please open an issue on the [GitHub repository](https://github.com/pacnpal/Pac-cogs).
