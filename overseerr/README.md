# Overseerr Cog for Red Discord Bot

This cog allows interaction with [Overseerr](https://overseerr.dev/) directly from Discord. Users can search for movies or TV shows, request them, and have admins approve requests. It's designed for servers with Overseerr set up for managing media requests.

## Installation

To install this cog, follow these steps:

1. Ensure you have Red-DiscordBot V3 installed.
2. Add the repository to your bot:

   ```
   [p]repo add Pac-cogs https://github.com/pacnpal/Pac-cogs
   ```

3. Install the Overseerr cog:

   ```
   [p]cog install Pac-cogs overseerr
   ```

4. Load the cog:

   ```
   [p]load overseerr
   ```

Replace `[p]` with your bot's prefix.


## Setup

Before using the cog, you'll need to configure it:

1. Set the Overseerr URL and API key:
    ```
    [p]setoverseerr url https://your.overseerr.instance 
    ```
2. Set the Overseerr API key:
    ```
    [p]setoverseerr api_key your_api_key
    ```
4. Set the admin role allowed to approve requests:
    ```
    [p]setadminrole @OverseerrAdmins
    ```

## Usage

Users can request movies or TV shows using the following command:

```
[p]request Movie/TV Show Name
```

Admins can approve requests using:

```
[p]approve request_id
```

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


## Support

If you encounter any issues or have questions, please open an issue on the [GitHub repository](https://github.com/pacnpal/Pac-cogs).
