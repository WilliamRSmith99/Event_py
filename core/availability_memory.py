"""
Persistent Availability Memory for Event Bot (Premium Feature).

Remembers users' typical availability patterns across events,
allowing them to auto-fill availability for new events.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Any, Optional, Set
from collections import defaultdict

from core.storage import read_json, write_json_atomic
from core.logging import get_logger
from core import entitlements
from core.entitlements import Feature

logger = get_logger(__name__)

AVAILABILITY_MEMORY_FILE = "availability_memory.json"


# =============================================================================
# Data Models
# =============================================================================

@dataclass
class TimeSlotPattern:
    """A pattern representing a user's typical availability."""
    day_of_week: int  # 0=Monday, 6=Sunday
    hour: int  # 0-23
    count: int = 1  # How many times they've been available at this time
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

    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "guild_id": self.guild_id,
            "patterns": [p.to_dict() for p in self.patterns],
            "last_updated": self.last_updated,
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "UserAvailabilityMemory":
        return UserAvailabilityMemory(
            user_id=data["user_id"],
            guild_id=data["guild_id"],
            patterns=[TimeSlotPattern.from_dict(p) for p in data.get("patterns", [])],
            last_updated=data.get("last_updated", datetime.utcnow().isoformat()),
        )

    def get_pattern(self, day_of_week: int, hour: int) -> Optional[TimeSlotPattern]:
        """Get a specific pattern if it exists."""
        for pattern in self.patterns:
            if pattern.day_of_week == day_of_week and pattern.hour == hour:
                return pattern
        return None

    def add_or_update_pattern(self, day_of_week: int, hour: int) -> None:
        """Add a new pattern or increment an existing one."""
        existing = self.get_pattern(day_of_week, hour)
        if existing:
            existing.count += 1
            existing.last_used = datetime.utcnow().isoformat()
        else:
            self.patterns.append(TimeSlotPattern(
                day_of_week=day_of_week,
                hour=hour,
                count=1,
            ))
        self.last_updated = datetime.utcnow().isoformat()

    def get_suggested_slots(self, min_count: int = 2) -> List[TimeSlotPattern]:
        """Get slots the user is frequently available at."""
        return sorted(
            [p for p in self.patterns if p.count >= min_count],
            key=lambda p: p.count,
            reverse=True
        )


# =============================================================================
# Storage Functions
# =============================================================================

def load_availability_memory() -> Dict[str, Dict[str, UserAvailabilityMemory]]:
    """Load all availability memory from storage."""
    try:
        raw = read_json(AVAILABILITY_MEMORY_FILE)
        result = {}
        for guild_id, users in raw.items():
            result[guild_id] = {
                user_id: UserAvailabilityMemory.from_dict(data)
                for user_id, data in users.items()
            }
        return result
    except FileNotFoundError:
        return {}


def save_availability_memory(data: Dict[str, Dict[str, UserAvailabilityMemory]]) -> None:
    """Save all availability memory to storage."""
    to_save = {
        guild_id: {
            user_id: memory.to_dict()
            for user_id, memory in users.items()
        }
        for guild_id, users in data.items()
    }
    write_json_atomic(AVAILABILITY_MEMORY_FILE, to_save)


# =============================================================================
# Public API
# =============================================================================

def get_user_memory(user_id: int, guild_id: int) -> Optional[UserAvailabilityMemory]:
    """
    Get a user's availability memory for a guild.

    Returns None if the guild doesn't have premium or no memory exists.
    """
    # Check if guild has premium
    if not entitlements.has_feature(guild_id, Feature.PERSISTENT_AVAILABILITY):
        return None

    all_memory = load_availability_memory()
    guild_memory = all_memory.get(str(guild_id), {})
    return guild_memory.get(str(user_id))


def record_availability(
    user_id: int,
    guild_id: int,
    availability_slots: List[datetime]
) -> bool:
    """
    Record a user's availability selections to build their pattern.

    Args:
        user_id: The Discord user ID
        guild_id: The Discord guild ID
        availability_slots: List of datetime objects the user selected

    Returns:
        True if recorded (premium), False if not recorded (free tier)
    """
    # Check if guild has premium
    if not entitlements.has_feature(guild_id, Feature.PERSISTENT_AVAILABILITY):
        return False

    all_memory = load_availability_memory()
    guild_key = str(guild_id)
    user_key = str(user_id)

    if guild_key not in all_memory:
        all_memory[guild_key] = {}

    if user_key not in all_memory[guild_key]:
        all_memory[guild_key][user_key] = UserAvailabilityMemory(
            user_id=user_id,
            guild_id=guild_id,
        )

    memory = all_memory[guild_key][user_key]

    for slot in availability_slots:
        memory.add_or_update_pattern(
            day_of_week=slot.weekday(),
            hour=slot.hour
        )

    save_availability_memory(all_memory)
    logger.info(f"Recorded {len(availability_slots)} availability slots for user {user_id} in guild {guild_id}")
    return True


def get_suggested_availability(
    user_id: int,
    guild_id: int,
    proposed_slots: List[datetime],
    min_count: int = 2
) -> List[datetime]:
    """
    Get suggested availability based on user's history.

    Args:
        user_id: The Discord user ID
        guild_id: The Discord guild ID
        proposed_slots: List of proposed datetime slots for the event
        min_count: Minimum times a slot must have been used to be suggested

    Returns:
        List of datetime slots the user is typically available at
    """
    memory = get_user_memory(user_id, guild_id)
    if not memory:
        return []

    suggested_patterns = memory.get_suggested_slots(min_count)
    if not suggested_patterns:
        return []

    # Build a set of (day_of_week, hour) tuples for fast lookup
    pattern_set = {(p.day_of_week, p.hour) for p in suggested_patterns}

    # Filter proposed slots to those matching user's patterns
    suggested = []
    for slot in proposed_slots:
        if (slot.weekday(), slot.hour) in pattern_set:
            suggested.append(slot)

    return suggested


def clear_user_memory(user_id: int, guild_id: int) -> bool:
    """Clear a user's availability memory for a guild."""
    all_memory = load_availability_memory()
    guild_key = str(guild_id)
    user_key = str(user_id)

    if guild_key in all_memory and user_key in all_memory[guild_key]:
        del all_memory[guild_key][user_key]
        save_availability_memory(all_memory)
        logger.info(f"Cleared availability memory for user {user_id} in guild {guild_id}")
        return True
    return False


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
        "last_updated": memory.last_updated,
    }
