"""Module for managing Discord role configurations"""

import logging
from typing import Dict, List, Set, Tuple, Optional, Any
import discord # type: ignore

try:
    # Try relative imports first
    from .exceptions import ConfigurationError as ConfigError
except ImportError:
    # Fall back to absolute imports if relative imports fail
    # from videoarchiver.config.exceptions import ConfigurationError as ConfigError

logger = logging.getLogger("RoleManager")


class RoleManager:
    """Manages Discord role configurations"""

    def __init__(self, config_manager):
        self.config_manager = config_manager

    async def check_user_roles(
        self,
        member: discord.Member
    ) -> Tuple[bool, Optional[str]]:
        """Check if user has permission based on allowed roles
        
        Args:
            member: Discord member to check
            
        Returns:
            Tuple[bool, Optional[str]]: (Has permission, Reason if denied)
            
        Raises:
            ConfigError: If role check fails
        """
        try:
            allowed_roles = await self.config_manager.get_setting(
                member.guild.id,
                "allowed_roles"
            )
            
            # If no roles are set, allow all users
            if not allowed_roles:
                return True, None

            # Check user roles
            user_roles = {role.id for role in member.roles}
            allowed_role_set = set(allowed_roles)
            
            if user_roles & allowed_role_set:  # Intersection
                return True, None
                
            # Get role names for error message
            missing_roles = await self._get_role_names(
                member.guild,
                allowed_role_set
            )
            return False, f"Missing required roles: {', '.join(missing_roles)}"
            
        except Exception as e:
            logger.error(f"Failed to check roles for user {member.id} in guild {member.guild.id}: {e}")
            raise ConfigError(f"Failed to check user roles: {str(e)}")

    async def add_allowed_role(
        self,
        guild_id: int,
        role_id: int
    ) -> None:
        """Add a role to allowed roles
        
        Args:
            guild_id: Guild ID
            role_id: Role ID to add
            
        Raises:
            ConfigError: If role cannot be added
        """
        try:
            await self.config_manager.add_to_list(
                guild_id,
                "allowed_roles",
                role_id
            )
        except Exception as e:
            logger.error(f"Failed to add allowed role {role_id}: {e}")
            raise ConfigError(f"Failed to add allowed role: {str(e)}")

    async def remove_allowed_role(
        self,
        guild_id: int,
        role_id: int
    ) -> None:
        """Remove a role from allowed roles
        
        Args:
            guild_id: Guild ID
            role_id: Role ID to remove
            
        Raises:
            ConfigError: If role cannot be removed
        """
        try:
            await self.config_manager.remove_from_list(
                guild_id,
                "allowed_roles",
                role_id
            )
        except Exception as e:
            logger.error(f"Failed to remove allowed role {role_id}: {e}")
            raise ConfigError(f"Failed to remove allowed role: {str(e)}")

    async def get_allowed_roles(
        self,
        guild: discord.Guild
    ) -> List[discord.Role]:
        """Get all allowed roles for a guild
        
        Args:
            guild: Discord guild
            
        Returns:
            List[discord.Role]: List of allowed roles
            
        Raises:
            ConfigError: If roles cannot be retrieved
        """
        try:
            settings = await self.config_manager.get_guild_settings(guild.id)
            role_ids = settings["allowed_roles"]
            
            roles = []
            invalid_roles = []
            
            for role_id in role_ids:
                role = guild.get_role(role_id)
                if role:
                    roles.append(role)
                else:
                    invalid_roles.append(role_id)
                    logger.warning(f"Invalid role {role_id} in guild {guild.id}")
            
            # Clean up invalid roles if found
            if invalid_roles:
                await self._remove_invalid_roles(guild.id, invalid_roles)
            
            return roles
            
        except Exception as e:
            logger.error(f"Failed to get allowed roles for guild {guild.id}: {e}")
            raise ConfigError(f"Failed to get allowed roles: {str(e)}")

    async def verify_role_hierarchy(
        self,
        guild: discord.Guild,
        role: discord.Role
    ) -> Tuple[bool, Optional[str]]:
        """Verify bot's role hierarchy position for managing a role
        
        Args:
            guild: Discord guild
            role: Role to check
            
        Returns:
            Tuple[bool, Optional[str]]: (Can manage role, Reason if not)
        """
        try:
            bot_member = guild.me
            bot_top_role = bot_member.top_role
            
            if role >= bot_top_role:
                return False, f"Role {role.name} is higher than or equal to bot's highest role"
                
            return True, None
            
        except Exception as e:
            logger.error(f"Error checking role hierarchy: {e}")
            return False, "Failed to check role hierarchy"

    async def _get_role_names(
        self,
        guild: discord.Guild,
        role_ids: Set[int]
    ) -> List[str]:
        """Get role names from role IDs
        
        Args:
            guild: Discord guild
            role_ids: Set of role IDs
            
        Returns:
            List[str]: List of role names
        """
        role_names = []
        for role_id in role_ids:
            role = guild.get_role(role_id)
            if role:
                role_names.append(role.name)
        return role_names

    async def _remove_invalid_roles(
        self,
        guild_id: int,
        role_ids: List[int]
    ) -> None:
        """Remove invalid roles from allowed roles
        
        Args:
            guild_id: Guild ID
            role_ids: List of invalid role IDs to remove
        """
        try:
            for role_id in role_ids:
                await self.remove_allowed_role(guild_id, role_id)
        except Exception as e:
            logger.error(f"Error removing invalid roles: {e}")

    async def get_role_info(
        self,
        guild: discord.Guild
    ) -> Dict[str, Any]:
        """Get role configuration information
        
        Args:
            guild: Discord guild
            
        Returns:
            Dict[str, Any]: Dictionary containing role information
        """
        try:
            allowed_roles = await self.get_allowed_roles(guild)
            bot_member = guild.me
            
            return {
                'allowed_roles': allowed_roles,
                'bot_top_role': bot_member.top_role,
                'bot_permissions': bot_member.guild_permissions,
                'role_count': len(allowed_roles)
            }
        except Exception as e:
            logger.error(f"Error getting role info: {e}")
            return {
                'allowed_roles': [],
                'bot_top_role': None,
                'bot_permissions': None,
                'role_count': 0
            }
