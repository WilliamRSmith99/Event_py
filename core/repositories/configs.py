"""
Configuration Repository for Event Bot.

Handles all database operations for guild configuration.
"""
import json
from typing import Dict, List, Optional, Any

from core.database import (
    get_cursor, transaction, execute_query, execute_one,
    execute_write, row_to_dict
)
from core.logging import get_logger
from core.conf import ServerConfigState

logger = get_logger(__name__)


class ConfigRepository:
    """Repository for guild configuration data operations."""

    @staticmethod
    def get_config(guild_id: int) -> ServerConfigState:
        """
        Get configuration for a guild.

        Creates a default config if one doesn't exist.

        Args:
            guild_id: Discord guild ID

        Returns:
            ServerConfigState for the guild
        """
        row = execute_one(
            "SELECT * FROM guild_configs WHERE guild_id = ?",
            (str(guild_id),)
        )

        if row:
            return ConfigRepository._row_to_config(dict(row))

        # Create default config
        config = ServerConfigState(guild_id=str(guild_id))
        ConfigRepository.save_config(config)
        return config

    @staticmethod
    def get_all_configs() -> Dict[str, ServerConfigState]:
        """
        Get all guild configurations.

        Returns:
            Dict mapping guild_id -> ServerConfigState
        """
        rows = execute_query("SELECT * FROM guild_configs")
        return {
            row["guild_id"]: ConfigRepository._row_to_config(dict(row))
            for row in rows
        }

    @staticmethod
    def save_config(config: ServerConfigState) -> bool:
        """
        Save or update a guild configuration.

        Args:
            config: ServerConfigState to save

        Returns:
            True if saved successfully
        """
        try:
            execute_write(
                """
                INSERT INTO guild_configs (
                    guild_id, admin_roles, event_organizer_roles, event_attendee_roles,
                    bulletin_channel, roles_and_permissions_settings_enabled,
                    bulletin_settings_enabled, display_settings_enabled,
                    notifications_enabled, default_reminder_minutes, notification_channel
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(guild_id) DO UPDATE SET
                    admin_roles = excluded.admin_roles,
                    event_organizer_roles = excluded.event_organizer_roles,
                    event_attendee_roles = excluded.event_attendee_roles,
                    bulletin_channel = excluded.bulletin_channel,
                    roles_and_permissions_settings_enabled = excluded.roles_and_permissions_settings_enabled,
                    bulletin_settings_enabled = excluded.bulletin_settings_enabled,
                    display_settings_enabled = excluded.display_settings_enabled,
                    notifications_enabled = excluded.notifications_enabled,
                    default_reminder_minutes = excluded.default_reminder_minutes,
                    notification_channel = excluded.notification_channel,
                    updated_at = datetime('now')
                """,
                (
                    str(config.guild_id),
                    json.dumps(config.admin_roles),
                    json.dumps(config.event_organizer_roles),
                    json.dumps(config.event_attendee_roles),
                    config.bulletin_channel,
                    1 if config.roles_and_permissions_settings_enabled else 0,
                    1 if config.bulletin_settings_enabled else 0,
                    1 if config.display_settings_enabled else 0,
                    1 if config.notifications_enabled else 0,
                    config.default_reminder_minutes,
                    config.notification_channel
                )
            )
            logger.debug(f"Saved config for guild {config.guild_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to save config: {e}")
            return False

    @staticmethod
    def delete_config(guild_id: int) -> bool:
        """
        Delete a guild's configuration.

        Args:
            guild_id: Discord guild ID

        Returns:
            True if deleted successfully
        """
        try:
            rows_affected = execute_write(
                "DELETE FROM guild_configs WHERE guild_id = ?",
                (str(guild_id),)
            )
            if rows_affected > 0:
                logger.info(f"Deleted config for guild {guild_id}")
            return rows_affected > 0

        except Exception as e:
            logger.error(f"Failed to delete config: {e}")
            return False

    @staticmethod
    def _row_to_config(row: dict) -> ServerConfigState:
        """Convert a database row to a ServerConfigState object."""
        return ServerConfigState(
            guild_id=row["guild_id"],
            admin_roles=json.loads(row.get("admin_roles", "[]")),
            event_organizer_roles=json.loads(row.get("event_organizer_roles", "[]")),
            event_attendee_roles=json.loads(row.get("event_attendee_roles", "[]")),
            bulletin_channel=row.get("bulletin_channel"),
            roles_and_permissions_settings_enabled=bool(row.get("roles_and_permissions_settings_enabled", 1)),
            bulletin_settings_enabled=bool(row.get("bulletin_settings_enabled", 0)),
            display_settings_enabled=bool(row.get("display_settings_enabled", 1)),
            notifications_enabled=bool(row.get("notifications_enabled", 1)),
            default_reminder_minutes=row.get("default_reminder_minutes", 60),
            notification_channel=row.get("notification_channel")
        )

    # =========================================================================
    # Convenience Methods
    # =========================================================================

    @staticmethod
    def update_admin_roles(guild_id: int, roles: List[int]) -> bool:
        """Update the admin roles for a guild."""
        try:
            execute_write(
                """
                UPDATE guild_configs
                SET admin_roles = ?, updated_at = datetime('now')
                WHERE guild_id = ?
                """,
                (json.dumps(roles), str(guild_id))
            )
            return True
        except Exception as e:
            logger.error(f"Failed to update admin roles: {e}")
            return False

    @staticmethod
    def update_bulletin_channel(guild_id: int, channel_id: Optional[str]) -> bool:
        """Update the bulletin channel for a guild."""
        try:
            execute_write(
                """
                UPDATE guild_configs
                SET bulletin_channel = ?, updated_at = datetime('now')
                WHERE guild_id = ?
                """,
                (channel_id, str(guild_id))
            )
            return True
        except Exception as e:
            logger.error(f"Failed to update bulletin channel: {e}")
            return False

    @staticmethod
    def update_notification_settings(
        guild_id: int,
        enabled: bool,
        default_reminder_minutes: int,
        channel_id: Optional[str]
    ) -> bool:
        """Update notification settings for a guild."""
        try:
            execute_write(
                """
                UPDATE guild_configs
                SET notifications_enabled = ?,
                    default_reminder_minutes = ?,
                    notification_channel = ?,
                    updated_at = datetime('now')
                WHERE guild_id = ?
                """,
                (1 if enabled else 0, default_reminder_minutes, channel_id, str(guild_id))
            )
            return True
        except Exception as e:
            logger.error(f"Failed to update notification settings: {e}")
            return False
