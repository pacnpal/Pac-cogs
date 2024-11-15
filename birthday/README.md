# Birthday Cog for Red-DiscordBot

This cog allows you to assign a special role to users on their birthday and send them a celebratory message with cake (or pie) emojis! Supports both traditional prefix commands, slash commands, and context menu commands.

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

Before using the cog, you need to set it up. You can use either prefix commands or slash commands:

1. Set the birthday role:

   ```
   [p]setrole @Birthday
   ```
   or
   ```
   /setrole @Birthday
   ```

   **Note:** The bot's role must be above the birthday role in the server's role hierarchy, but users assigning the birthday role do not need to have a role above it.

2. Add roles that can use the birthday command:

   ```
   [p]birthdayallowrole @Moderator
   ```
   or
   ```
   /birthdayallowrole @Moderator
   ```

3. (Optional) Set the timezone for role expiration:

   ```
   [p]settimezone America/New_York
   ```
   or
   ```
   /settimezone America/New_York
   ```

4. (Optional) Set a specific channel for birthday announcements:

   ```
   [p]setchannel #birthdays
   ```
   or
   ```
   /setchannel #birthdays
   ```

   If not set, the birthday message will be sent in the channel where the command is used.

## Usage

To assign or remove the birthday role from a user, you can use any of these methods:

1. Commands:
   ```
   [p]birthday @User
   ```
   or
   ```
   /birthday @User
   ```

   To remove:
   ```
   [p]removebirthday @User
   ```
   or
   ```
   /removebirthday @User
   ```

2. Context Menu:
   - Right-click on a user and select "Apps > Give Birthday Role" to assign
   - Right-click on a user and select "Apps > Remove Birthday Role" to remove

When assigning the role, this will give the user the birthday role and send a celebratory message with random cake (or pie) emojis. The role will be automatically removed at midnight in the specified timezone.

## Features

- Assigns a special birthday role to users
- Sends a celebratory message with random cake (or pie) emojis
- Automatically removes the birthday role at midnight
- Configurable timezone for role expiration
- Option to set a specific channel for birthday announcements (defaults to the channel where the command is used)
- Restricts usage of the birthday command to specified roles
- Users can assign the birthday role without needing a role higher than it in the hierarchy
- Full slash command and context menu support
- Persistent birthday role removal scheduling (survives bot restarts)
- Birthday role removal task checking
- Manual birthday role removal option

## Commands

All commands support both prefix and slash command syntax:

### Admin Commands
- `[p]setrole` or `/setrole`: Set the birthday role
- `[p]birthdayallowrole` or `/birthdayallowrole`: Add a role that can use the birthday command
- `[p]birthdayremoverole` or `/birthdayremoverole`: Remove a role from using the birthday command
- `[p]settimezone` or `/settimezone`: Set the timezone for the birthday role expiration
- `[p]setchannel` or `/setchannel`: Set the channel for birthday announcements

### User Commands
- `[p]birthday` or `/birthday`: Assign the birthday role to a user
- `[p]removebirthday` or `/removebirthday`: Remove the birthday role from a user
- Context Menu > "Give Birthday Role": Right-click a user to assign the birthday role
- Context Menu > "Remove Birthday Role": Right-click a user to remove the birthday role
- `[p]bdaycheck` or `/bdaycheck`: Check upcoming birthday role removal tasks

## Support

If you encounter any issues or have questions, please open an issue on the [GitHub repository](https://github.com/pacnpal/Pac-cogs).
