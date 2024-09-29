# Birthday Cog for Red-DiscordBot

This cog allows you to assign a special role to users on their birthday and send them a celebratory message with cake (or pie) emojis!

## Installation

To install this cog, follow these steps:

1. Ensure you have Red-DiscordBot V3 installed.
2. Add the repository to your bot:
   ```
   [p]repo add Pac-cogs https://github.com/pacnpal/Pac-cogs
   ```
3. Install the Birthday cog:
   ```
   [p]cog install Pac-cogs birthday
   ```
4. Load the cog:
   ```
   [p]load birthday
   ```

Replace `[p]` with your bot's prefix.

## Setup

Before using the cog, you need to set it up:

1. Set the birthday role:
   ```
   [p]birthdayset role @Birthday
   ```
   **Note:** The bot's role must be above the birthday role in the server's role hierarchy, but users assigning the birthday role do not need to have a role above it.

2. Add roles that can use the birthday command:
   ```
   [p]birthdayset addrole @Moderator
   ```
3. (Optional) Set the timezone for role expiration:
   ```
   [p]birthdayset timezone America/New_York
   ```
4. (Optional) Set a specific channel for birthday announcements:
   ```
   [p]birthdayset channel #birthdays
   ```
   If not set, the birthday message will be sent in the channel where the command is used.

## Usage

To assign the birthday role to a user:
```
[p]birthday @User
```

This will assign the birthday role to the user and send a celebratory message with random cake (or pie) emojis. The role will be automatically removed at midnight in the specified timezone.

## Features

- Assigns a special birthday role to users
- Sends a celebratory message with random cake (or pie) emojis
- Automatically removes the birthday role at midnight
- Configurable timezone for role expiration
- Option to set a specific channel for birthday announcements (defaults to the channel where the command is used)
- Restricts usage of the birthday command to specified roles
- Users can assign the birthday role without needing a role higher than it in the hierarchy

## Commands

- `[p]birthdayset role`: Set the birthday role
- `[p]birthdayset addrole`: Add a role that can use the birthday command
- `[p]birthdayset removerole`: Remove a role from using the birthday command
- `[p]birthdayset timezone`: Set the timezone for the birthday role expiration
- `[p]birthdayset channel`: Set the channel for birthday announcements
- `[p]birthday`: Assign the birthday role to a user

## Support

If you encounter any issues or have questions, please open an issue on the [GitHub repository](https://github.com/pacnpal/Pac-cogs).