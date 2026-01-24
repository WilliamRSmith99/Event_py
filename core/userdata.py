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


def get_user_time_format(user_id: int) -> Optional[bool]:
    """
    Get a user's time format preference.

    Args:
        user_id: Discord user ID

    Returns:
        True for 24hr, False for 12hr, None if not set (use server default)
    """
    return UserRepository.get_time_format(int(user_id))


def set_user_time_format(user_id: int, use_24hr: bool) -> bool:
    """
    Set a user's time format preference.

    Args:
        user_id: Discord user ID
        use_24hr: True for 24-hour format, False for 12-hour

    Returns:
        True if set successfully
    """
    return UserRepository.set_time_format(int(user_id), use_24hr)


def clear_user_time_format(user_id: int) -> bool:
    """
    Clear a user's time format preference (revert to server default).

    Args:
        user_id: Discord user ID

    Returns:
        True if cleared successfully
    """
    return UserRepository.clear_time_format(int(user_id))


def get_effective_time_format(user_id: int, guild_id: int) -> bool:
    """
    Get the effective time format for a user in a guild.

    Checks user preference first, falls back to server setting.

    Args:
        user_id: Discord user ID
        guild_id: Discord guild ID

    Returns:
        True for 24hr format, False for 12hr format
    """
    # Check user preference first
    user_pref = get_user_time_format(user_id)
    if user_pref is not None:
        return user_pref

    # Fall back to server setting
    from core import conf
    server_config = conf.get_config(guild_id)
    if server_config:
        return getattr(server_config, "use_24hr_time", False)

    return False  # Default to 12hr
