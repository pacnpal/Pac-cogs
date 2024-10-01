# Overseerr Cog for Red Discord Bot

This cog allows interaction with [Overseerr](https://overseerr.dev/) directly from Discord. Users can search for movies or TV shows, request them, and have admins approve requests. It's designed for servers with Overseerr set up for managing media requests.

## Features
- **Set Overseerr URL and API key**: Admins can configure the Overseerr URL and API key for API interactions.
- **Search and request media**: Users can search for movies or TV shows and request them directly in Discord.
- **Media availability status**: The cog checks if media is already available or has been requested before making new requests.
- **Approve requests**: Admins with the appropriate role can approve Overseerr requests within Discord.

## Commands

### Admin Commands
- **`[p]setoverseerr <url> <api_key>`**
  - Set the Overseerr URL and API key for the bot to communicate with Overseerr.
  - Example: `[p]setoverseerr https://my.overseerr.url abcdefghijklmnop`

- **`[p]setadminrole <role_name>`**
  - Set the name of the admin role that is allowed to approve Overseerr requests.
  - Example: `[p]setadminrole Overseerr Admin`

### User Commands
- **`[p]request <media name>`**
  - Search for a movie or TV show and request it if it's not already available or requested.
  - Example: `[p]request The Matrix`

- **`[p]approve <request_id>`**
  - Approve a media request by its request ID (requires the admin role).
  - Example: `[p]approve 123`

## Installation

1. Add the cog to your Red instance:
   ```bash
   [p]load overseerr
