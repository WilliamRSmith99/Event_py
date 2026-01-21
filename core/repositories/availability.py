"""
Availability Memory Repository for Event Bot.

Handles all database operations for persistent availability patterns
(Premium Feature).
"""
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple

from core.database import (
    get_cursor, transaction, execute_query, execute_one,
    execute_write
)
from core.logging import get_logger

logger = get_logger(__name__)


class AvailabilityMemoryRepository:
    """Repository for availability pattern data operations."""

    @staticmethod
    def get_user_patterns(
        user_id: int,
        guild_id: int
    ) -> List[Dict[str, Any]]:
        """
        Get all availability patterns for a user in a guild.

        Args:
            user_id: Discord user ID
            guild_id: Discord guild ID

        Returns:
            List of pattern dicts with day_of_week, hour, count, last_used
        """
        rows = execute_query(
            """
            SELECT day_of_week, hour, count, last_used
            FROM availability_patterns
            WHERE user_id = ? AND guild_id = ?
            ORDER BY count DESC
            """,
            (str(user_id), str(guild_id))
        )

        return [dict(row) for row in rows]

    @staticmethod
    def get_frequent_patterns(
        user_id: int,
        guild_id: int,
        min_count: int = 2
    ) -> List[Dict[str, Any]]:
        """
        Get frequently used availability patterns.

        Args:
            user_id: Discord user ID
            guild_id: Discord guild ID
            min_count: Minimum occurrence count

        Returns:
            List of frequent pattern dicts
        """
        rows = execute_query(
            """
            SELECT day_of_week, hour, count, last_used
            FROM availability_patterns
            WHERE user_id = ? AND guild_id = ? AND count >= ?
            ORDER BY count DESC
            """,
            (str(user_id), str(guild_id), min_count)
        )

        return [dict(row) for row in rows]

    @staticmethod
    def record_availability(
        user_id: int,
        guild_id: int,
        slots: List[Tuple[int, int]]
    ) -> bool:
        """
        Record availability selections to build patterns.

        Args:
            user_id: Discord user ID
            guild_id: Discord guild ID
            slots: List of (day_of_week, hour) tuples

        Returns:
            True if recorded successfully
        """
        try:
            with transaction() as cursor:
                for day_of_week, hour in slots:
                    cursor.execute(
                        """
                        INSERT INTO availability_patterns (
                            user_id, guild_id, day_of_week, hour, count
                        ) VALUES (?, ?, ?, ?, 1)
                        ON CONFLICT(user_id, guild_id, day_of_week, hour) DO UPDATE SET
                            count = count + 1,
                            last_used = datetime('now')
                        """,
                        (str(user_id), str(guild_id), day_of_week, hour)
                    )

            logger.debug(
                f"Recorded {len(slots)} availability slots for user {user_id} "
                f"in guild {guild_id}"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to record availability: {e}")
            return False

    @staticmethod
    def clear_user_patterns(user_id: int, guild_id: int) -> bool:
        """
        Clear all availability patterns for a user in a guild.

        Args:
            user_id: Discord user ID
            guild_id: Discord guild ID

        Returns:
            True if cleared successfully
        """
        try:
            execute_write(
                """
                DELETE FROM availability_patterns
                WHERE user_id = ? AND guild_id = ?
                """,
                (str(user_id), str(guild_id))
            )
            logger.info(f"Cleared availability patterns for user {user_id} in guild {guild_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to clear patterns: {e}")
            return False

    @staticmethod
    def get_pattern_stats(user_id: int, guild_id: int) -> Optional[Dict[str, Any]]:
        """
        Get statistics about a user's availability patterns.

        Args:
            user_id: Discord user ID
            guild_id: Discord guild ID

        Returns:
            Dict with statistics or None if no patterns
        """
        patterns = AvailabilityMemoryRepository.get_user_patterns(user_id, guild_id)

        if not patterns:
            return None

        total_patterns = len(patterns)
        total_selections = sum(p["count"] for p in patterns)
        frequent = [p for p in patterns if p["count"] >= 2]

        day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        top_slots = []
        for p in frequent[:5]:
            hour = p["hour"]
            hour_str = f"{hour % 12 or 12}{'AM' if hour < 12 else 'PM'}"
            top_slots.append(f"{day_names[p['day_of_week']]} {hour_str} ({p['count']}x)")

        last_used = max((p["last_used"] for p in patterns), default=None)

        return {
            "total_patterns": total_patterns,
            "total_selections": total_selections,
            "frequent_count": len(frequent),
            "top_slots": top_slots,
            "last_updated": last_used
        }

    @staticmethod
    def get_suggested_slots(
        user_id: int,
        guild_id: int,
        proposed_slots: List[Tuple[int, int]],
        min_count: int = 2
    ) -> List[Tuple[int, int]]:
        """
        Get suggested slots based on user's history.

        Args:
            user_id: Discord user ID
            guild_id: Discord guild ID
            proposed_slots: List of (day_of_week, hour) tuples to filter
            min_count: Minimum pattern count to suggest

        Returns:
            Filtered list of slots the user frequently uses
        """
        frequent = AvailabilityMemoryRepository.get_frequent_patterns(
            user_id, guild_id, min_count
        )

        if not frequent:
            return []

        # Build set for fast lookup
        pattern_set = {(p["day_of_week"], p["hour"]) for p in frequent}

        # Filter proposed slots
        return [slot for slot in proposed_slots if slot in pattern_set]

    @staticmethod
    def cleanup_old_patterns(older_than_days: int = 180) -> int:
        """
        Clean up old, infrequently used patterns.

        Args:
            older_than_days: Delete patterns not used in this many days

        Returns:
            Number of patterns deleted
        """
        try:
            return execute_write(
                """
                DELETE FROM availability_patterns
                WHERE last_used < datetime('now', '-' || ? || ' days')
                AND count < 3
                """,
                (older_than_days,)
            )

        except Exception as e:
            logger.error(f"Failed to cleanup patterns: {e}")
            return 0

    @staticmethod
    def get_guild_stats(guild_id: int) -> Dict[str, Any]:
        """
        Get availability pattern statistics for a guild.

        Args:
            guild_id: Discord guild ID

        Returns:
            Dict with guild statistics
        """
        user_count = execute_one(
            """
            SELECT COUNT(DISTINCT user_id) as count
            FROM availability_patterns
            WHERE guild_id = ?
            """,
            (str(guild_id),)
        )

        total_patterns = execute_one(
            """
            SELECT COUNT(*) as count
            FROM availability_patterns
            WHERE guild_id = ?
            """,
            (str(guild_id),)
        )

        return {
            "users_with_patterns": user_count["count"] if user_count else 0,
            "total_patterns": total_patterns["count"] if total_patterns else 0
        }
