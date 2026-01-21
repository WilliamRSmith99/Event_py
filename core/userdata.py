"""
User data management for Event Bot.

Handles user timezones and preferences.
Uses SQLite database via UserRepository for persistence.
"""
from typing import Optional

from core.repositories.users import UserRepository
from core.logging import get_logger

logger = get_logger(__name__)


def set_user_timezone(user_id: int, timezone_str: str) -> bool:
    """
    Set a user's timezone.

    Args:
        user_id: Discord user ID
        timezone_str: IANA timezone string (e.g., 'America/New_York')

    Returns:
        True if set successfully
    """
    return UserRepository.set_timezone(int(user_id), timezone_str)


def get_user_timezone(user_id: int) -> Optional[str]:
    """
    Get a user's timezone.

    Args:
        user_id: Discord user ID

    Returns:
        Timezone string or None if not set
    """
    return UserRepository.get_timezone(int(user_id))
