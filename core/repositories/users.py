"""
User Repository for Event Bot.

Handles all database operations for user data (timezones, etc.).
"""
from typing import Dict, Optional

from core.database import (
    execute_query, execute_one, execute_write
)
from core.logging import get_logger

logger = get_logger(__name__)


class UserRepository:
    """Repository for user data operations."""

    @staticmethod
    def get_timezone(user_id: int) -> Optional[str]:
        """
        Get a user's timezone.

        Args:
            user_id: Discord user ID

        Returns:
            Timezone string or None if not set
        """
        row = execute_one(
            "SELECT timezone FROM user_data WHERE user_id = ?",
            (str(user_id),)
        )
        return row["timezone"] if row else None

    @staticmethod
    def set_timezone(user_id: int, timezone: str) -> bool:
        """
        Set a user's timezone.

        Args:
            user_id: Discord user ID
            timezone: IANA timezone string (e.g., 'America/New_York')

        Returns:
            True if set successfully
        """
        try:
            execute_write(
                """
                INSERT INTO user_data (user_id, timezone)
                VALUES (?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    timezone = excluded.timezone,
                    updated_at = datetime('now')
                """,
                (str(user_id), timezone)
            )
            logger.debug(f"Set timezone for user {user_id}: {timezone}")
            return True

        except Exception as e:
            logger.error(f"Failed to set timezone: {e}")
            return False

    @staticmethod
    def get_all_timezones() -> Dict[str, str]:
        """
        Get all user timezones.

        Returns:
            Dict mapping user_id -> timezone
        """
        rows = execute_query("SELECT user_id, timezone FROM user_data WHERE timezone IS NOT NULL")
        return {row["user_id"]: row["timezone"] for row in rows}

    @staticmethod
    def delete_user_data(user_id: int) -> bool:
        """
        Delete all data for a user.

        Args:
            user_id: Discord user ID

        Returns:
            True if deleted successfully
        """
        try:
            execute_write(
                "DELETE FROM user_data WHERE user_id = ?",
                (str(user_id),)
            )
            logger.info(f"Deleted user data for {user_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to delete user data: {e}")
            return False

    @staticmethod
    def get_user_count() -> int:
        """Get the total number of users with data."""
        row = execute_one("SELECT COUNT(*) as count FROM user_data")
        return row["count"] if row else 0

    @staticmethod
    def get_time_format(user_id: int) -> Optional[bool]:
        """
        Get a user's time format preference.

        Args:
            user_id: Discord user ID

        Returns:
            True for 24hr, False for 12hr, None if not set (use server default)
        """
        row = execute_one(
            "SELECT use_24hr_time FROM user_data WHERE user_id = ?",
            (str(user_id),)
        )
        if row and row["use_24hr_time"] is not None:
            return bool(row["use_24hr_time"])
        return None

    @staticmethod
    def set_time_format(user_id: int, use_24hr: bool) -> bool:
        """
        Set a user's time format preference.

        Args:
            user_id: Discord user ID
            use_24hr: True for 24-hour format, False for 12-hour

        Returns:
            True if set successfully
        """
        try:
            execute_write(
                """
                INSERT INTO user_data (user_id, use_24hr_time)
                VALUES (?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    use_24hr_time = excluded.use_24hr_time,
                    updated_at = datetime('now')
                """,
                (str(user_id), 1 if use_24hr else 0)
            )
            logger.debug(f"Set time format for user {user_id}: {'24hr' if use_24hr else '12hr'}")
            return True

        except Exception as e:
            logger.error(f"Failed to set time format: {e}")
            return False

    @staticmethod
    def clear_time_format(user_id: int) -> bool:
        """
        Clear a user's time format preference (revert to server default).

        Args:
            user_id: Discord user ID

        Returns:
            True if cleared successfully
        """
        try:
            execute_write(
                """
                UPDATE user_data SET use_24hr_time = NULL, updated_at = datetime('now')
                WHERE user_id = ?
                """,
                (str(user_id),)
            )
            logger.debug(f"Cleared time format for user {user_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to clear time format: {e}")
            return False
