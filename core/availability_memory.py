"""
Persistent Availability Memory for Event Bot (Premium Feature).

Remembers users' typical availability patterns across events,
allowing pre-selection of historically common hours in /register.

Backed by SQLite availability_patterns table (was: availability_memory.json).
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Any, Optional

from core.database import execute_one, execute_query, transaction
from core.logging import get_logger
from core import entitlements
from core.entitlements import Feature

logger = get_logger(__name__)


# =============================================================================
# Data Models
# =============================================================================

@dataclass
class TimeSlotPattern:
    """A pattern representing a user's typical availability."""
    day_of_week: int  # 0=Monday, 6=Sunday
    hour: int         # 0-23
    count: int = 1
    last_used: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "day_of_week": self.day_of_week,
            "hour": self.hour,
            "count": self.count,
            "last_used": self.last_used,
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "TimeSlotPattern":
        return TimeSlotPattern(
            day_of_week=data["day_of_week"],
            hour=data["hour"],
            count=data.get("count", 1),
            last_used=data.get("last_used", datetime.utcnow().isoformat()),
        )


@dataclass
class UserAvailabilityMemory:
    """A user's availability patterns for a guild."""
    user_id: int
    guild_id: int
    patterns: List[TimeSlotPattern] = field(default_factory=list)
    last_updated: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def get_pattern(self, day_of_week: int, hour: int) -> Optional[TimeSlotPattern]:
        for pattern in self.patterns:
            if pattern.day_of_week == day_of_week and pattern.hour == hour:
                return pattern
        return None

    def get_suggested_slots(self, min_count: int = 2) -> List[TimeSlotPattern]:
        """Get slots the user is frequently available at."""
        return sorted(
            [p for p in self.patterns if p.count >= min_count],
            key=lambda p: p.count,
            reverse=True,
        )


# =============================================================================
# Public API
# =============================================================================

def get_user_memory(user_id: int, guild_id: int) -> Optional[UserAvailabilityMemory]:
    """
    Get a user's availability patterns for a guild.
    Returns None if the guild doesn't have premium or no patterns exist.
    """
    if not entitlements.has_feature(guild_id, Feature.PERSISTENT_AVAILABILITY):
        return None

    rows = execute_query(
        "SELECT * FROM availability_patterns WHERE user_id = ? AND guild_id = ?",
        (str(user_id), str(guild_id)),
    )
    if not rows:
        return None

    patterns = [
        TimeSlotPattern(
            day_of_week=r["day_of_week"],
            hour=r["hour"],
            count=r["count"],
            last_used=r["last_used"],
        )
        for r in rows
    ]
    return UserAvailabilityMemory(user_id=user_id, guild_id=guild_id, patterns=patterns)


def record_availability(
    user_id: int,
    guild_id: int,
    availability_slots: List[datetime],
) -> bool:
    """
    Record a user's availability selections to build their pattern.

    Args:
        user_id: The Discord user ID
        guild_id: The Discord guild ID
        availability_slots: List of datetime objects the user selected

    Returns:
        True if recorded (premium guild), False otherwise.
    """
    if not entitlements.has_feature(guild_id, Feature.PERSISTENT_AVAILABILITY):
        return False

    now_iso = datetime.utcnow().isoformat()
    with transaction() as cursor:
        for slot in availability_slots:
            cursor.execute(
                """
                INSERT INTO availability_patterns (user_id, guild_id, day_of_week, hour, count, last_used)
                VALUES (?, ?, ?, ?, 1, ?)
                ON CONFLICT(user_id, guild_id, day_of_week, hour) DO UPDATE SET
                    count     = count + 1,
                    last_used = excluded.last_used
                """,
                (str(user_id), str(guild_id), slot.weekday(), slot.hour, now_iso),
            )

    logger.info(
        f"Recorded {len(availability_slots)} availability slots "
        f"for user {user_id} in guild {guild_id}"
    )
    return True


def get_suggested_availability(
    user_id: int,
    guild_id: int,
    proposed_slots: List[datetime],
    min_count: int = 2,
) -> List[datetime]:
    """
    Filter proposed_slots to those matching the user's historical patterns.

    Returns the subset of proposed_slots the user has been available at
    (same day-of-week + hour) at least min_count times.
    """
    memory = get_user_memory(user_id, guild_id)
    if not memory:
        return []

    pattern_set = {(p.day_of_week, p.hour) for p in memory.get_suggested_slots(min_count)}
    return [s for s in proposed_slots if (s.weekday(), s.hour) in pattern_set]


def clear_user_memory(user_id: int, guild_id: int) -> bool:
    """Clear all availability patterns for a user in a guild."""
    with transaction() as cursor:
        cursor.execute(
            "DELETE FROM availability_patterns WHERE user_id = ? AND guild_id = ?",
            (str(user_id), str(guild_id)),
        )
        deleted = cursor.rowcount > 0
    if deleted:
        logger.info(f"Cleared availability memory for user {user_id} in guild {guild_id}")
    return deleted


def get_memory_stats(user_id: int, guild_id: int) -> Optional[Dict[str, Any]]:
    """Get statistics about a user's availability memory."""
    memory = get_user_memory(user_id, guild_id)
    if not memory:
        return None

    total_patterns = len(memory.patterns)
    total_selections = sum(p.count for p in memory.patterns)
    frequent_patterns = memory.get_suggested_slots(min_count=2)

    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    top_slots = []
    for p in frequent_patterns[:5]:
        hour_str = f"{p.hour % 12 or 12}{'AM' if p.hour < 12 else 'PM'}"
        top_slots.append(f"{day_names[p.day_of_week]} {hour_str} ({p.count}x)")

    return {
        "total_patterns": total_patterns,
        "total_selections": total_selections,
        "frequent_count": len(frequent_patterns),
        "top_slots": top_slots,
    }
