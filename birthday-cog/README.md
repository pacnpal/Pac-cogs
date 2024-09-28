# Birthday Cog for Red-DiscordBot

This cog for [Red-DiscordBot](https://github.com/Cog-Creators/Red-DiscordBot) allows server administrators to assign a special "birthday role" to users until midnight Pacific Time.

## Features

- Assign a birthday role to a user that automatically expires at midnight Pacific Time
- Restrict usage of the birthday command to specific roles
- Ignore role hierarchy when assigning the birthday role
- Admin commands to set up the birthday role and manage permissions

## Installation

To install this cog, follow these steps:

1. Ensure you have Red-DiscordBot V3 installed.
2. Add the repository to your bot:
   ```
   [p]repo add Pac-cogs https://github.com/pacnpal/Pac-cogs
   ```
3. Install the cog:
   ```
   [p]cog install birthday-cog birthday
   ```

## Usage

After installation, load the cog with:
```
[p]load birthday
```

### Admin Setup

Before the cog can be used, an admin needs to set it up:

1. Set the birthday role:
   ```
   [p]birthdayset role @BirthdayRole
   ```
2. Add roles that can use the birthday command:
   ```
   [p]birthdayset addrole @AllowedRole
   ```

### Using the Birthday Command

Users with allowed roles can assign the birthday role to a member:
```
[p]birthday @User
```

The birthday role will be automatically removed at midnight Pacific Time.

## Commands

- `[p]birthdayset role @Role`: Set the birthday role
- `[p]birthdayset addrole @Role`: Add a role that can use the birthday command
- `[p]birthdayset removerole @Role`: Remove a role from using the birthday command
- `[p]birthday @User`: Assign the birthday role to a user

## License

This project is licensed under the Creative Commons Attribution 4.0 International License - see the [LICENSE](LICENSE) file for details.
