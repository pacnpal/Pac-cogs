# Overseerr Cog for Red Discord Bot

This cog allows interaction with [Overseerr](https://overseerr.dev/) directly from Discord. Users can search for movies or TV shows, request them, and have admins approve requests. It's designed for servers with Overseerr set up for managing media requests. Supports both traditional prefix commands and slash commands.

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

Before using the cog, you need to configure it. You can use either prefix commands or slash commands:

1. Set the Overseerr URL:
    ```
    [p]seturl https://your.overseerr.instance 
    ```
    or
    ```
    /seturl https://your.overseerr.instance
    ```

2. Set the Overseerr API key:
    ```
    [p]setapikey your_api_key
    ```
    or
    ```
    /setapikey your_api_key
    ```

3. (Optional) Set the admin role name for approvals:
    ```
    [p]setadminrole "Overseerr Admin"
    ```
    or
    ```
    /setadminrole "Overseerr Admin"
    ```

## Usage

### Requesting Media

To search for and request media:

```
[p]request Movie/TV Show Name
```
or
```
/request Movie/TV Show Name
```

This will:
1. Search for the media on Overseerr
2. Display an interactive select menu with up to 25 results
3. Show media type, release date, and current status (Available/Not Available/Requested) for each result
4. Allow you to select the desired title from the menu
5. Automatically check if the media is already available or requested before submitting a new request

### Approving Requests

Admins can approve requests using:

```
[p]approve request_id
```
or
```
/approve request_id
```

## Features

- **Interactive Media Selection**: Users get a dropdown menu of search results with detailed information
- **Smart Status Checking**: Automatically checks if media is already available or requested
- **Detailed Results**: Shows media type, release date, and availability status for each result
- **Admin Approval System**: Role-based approval system for managing requests
- **Full API Integration**: Direct integration with Overseerr's API for real-time status updates
- **Hybrid Commands**: Supports both traditional prefix commands and Discord slash commands
- **Error Handling**: Comprehensive error messages and user feedback
- **Permission Management**: Role-based access control for admin functions

## Commands

All commands support both prefix and slash command syntax:

### Admin Commands
- **`[p]seturl <url>`** or **`/seturl <url>`**
  - Set the Overseerr URL for API communication
  - Example: `[p]seturl https://your-overseerr-url` or `/seturl https://your-overseerr-url`

- **`[p]setapikey <apikey>`** or **`/setapikey <apikey>`**
  - Set the Overseerr API Key (found in your Overseerr settings)
  - Example: `[p]setapikey 4OK6WLU8Fv2T...` or `/setapikey 4OK6WLU8Fv2T...`

- **`[p]setadminrole <role_name>`** or **`/setadminrole <role_name>`**
  - Set the admin role for request approvals
  - Example: `[p]setadminrole "Overseerr Admin"` or `/setadminrole "Overseerr Admin"`

### User Commands
- **`[p]request <media name>`** or **`/request <media name>`**
  - Search for and request movies or TV shows
  - Displays an interactive select menu with detailed media information
  - Automatically checks availability status
  - Example: `[p]request The Matrix` or `/request The Matrix`

- **`[p]approve <request_id>`** or **`/approve <request_id>`**
  - Approve a media request (requires admin role)
  - Example: `[p]approve 123` or `/approve 123`

## Support

If you encounter any issues or have questions, please open an issue on the [GitHub repository](https://github.com/pacnpal/Pac-cogs).
