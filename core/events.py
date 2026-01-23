from core.storage import read_json, write_json_atomic
from core.logging import get_logger, log_event_action
from dataclasses import dataclass, field
from datetime import datetime
from typing import Set, Dict, Any, Optional, Union, Tuple, List
from enum import Enum
import uuid

logger = get_logger(__name__)


# ========== Recurring Event Types ==========

class RecurrenceType(Enum):
    """Types of event recurrence patterns."""
    NONE = "none"           # One-time event
    DAILY = "daily"         # Every day
    WEEKLY = "weekly"       # Same day every week
    BIWEEKLY = "biweekly"   # Every two weeks
    MONTHLY = "monthly"     # Same day of month


@dataclass
class RecurrenceConfig:
    """Configuration for recurring events (Premium feature)."""
    type: RecurrenceType = RecurrenceType.NONE
    interval: int = 1  # Every N periods (e.g., every 2 weeks)
    end_date: Optional[str] = None  # ISO format, None = no end
    occurrences: Optional[int] = None  # Max occurrences, None = unlimited
    parent_event_id: Optional[str] = None  # For child instances

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type.value,
            "interval": self.interval,
            "end_date": self.end_date,
            "occurrences": self.occurrences,
            "parent_event_id": self.parent_event_id,
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "RecurrenceConfig":
        return RecurrenceConfig(
            type=RecurrenceType(data.get("type", "none")),
            interval=data.get("interval", 1),
            end_date=data.get("end_date"),
            occurrences=data.get("occurrences"),
            parent_event_id=data.get("parent_event_id"),
        )


# ========== Event State Model ==========

@dataclass
class EventState:
    guild_id: str
    event_name: str
    max_attendees: str
    organizer: str
    organizer_cname: str
    confirmed_date: str
    event_id: Optional[str] = field(default_factory=lambda: str(uuid.uuid4()))
    bulletin_channel_id: Optional[int] = None
    bulletin_message_id: Optional[int] = None
    bulletin_thread_id: Optional[int] = None
    rsvp: list[str] = field(default_factory=list)
    slots: list[str] = field(default_factory=list)
    availability: Dict[str, Dict[str, str]] = field(default_factory=dict)
    waitlist: Dict[str, Dict[str, str]] = field(default_factory=dict)
    availability_to_message_map: Dict[str, Dict[str, Union[int, str]]] = field(default_factory=dict)
    # Format: { utc_iso: { "thread_id": int, "message_id": int, "embed_index": int, "field_name": str } }

    # Premium features
    recurrence: Optional[RecurrenceConfig] = None  # Recurring event config (Premium)

    # Archiving
    archived_at: Optional[str] = None  # ISO format when event was archived
    created_at: Optional[str] = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "guild_id": self.guild_id,
            "event_name": self.event_name,
            "event_id": self.event_id,
            "max_attendees": self.max_attendees,
            "organizer": self.organizer,
            "organizer_cname": self.organizer_cname,
            "confirmed_date": self.confirmed_date,
            "bulletin_channel_id": self.bulletin_channel_id,
            "bulletin_message_id": self.bulletin_message_id,
            "bulletin_thread_id": self.bulletin_thread_id,
            "rsvp": self.rsvp,
            "slots": self.slots,
            "availability": self.availability,
            "waitlist": self.waitlist,
            "availability_to_message_map": self.availability_to_message_map,
            "archived_at": self.archived_at,
            "created_at": self.created_at,
        }
        # Only include recurrence if set
        if self.recurrence:
            result["recurrence"] = self.recurrence.to_dict()
        return result

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "EventState":
        recurrence = None
        if "recurrence" in data and data["recurrence"]:
            recurrence = RecurrenceConfig.from_dict(data["recurrence"])

        return EventState(
            guild_id=data["guild_id"],
            event_name=data["event_name"],
            event_id=data.get("event_id", str(uuid.uuid4())),
            max_attendees=data["max_attendees"],
            organizer=data["organizer"],
            organizer_cname=data["organizer_cname"],
            confirmed_date=data["confirmed_date"],
            bulletin_channel_id=data.get("bulletin_channel_id"),
            bulletin_message_id=data.get("bulletin_message_id"),
            bulletin_thread_id=data.get("bulletin_thread_id"),
            rsvp=data.get("rsvp", []),
            slots=data.get("slots", []),
            availability=data.get("availability", {}),
            waitlist=data.get("waitlist", {}),
            availability_to_message_map=data.get("availability_to_message_map", {}),
            recurrence=recurrence,
            archived_at=data.get("archived_at"),
            created_at=data.get("created_at"),
        )

    @property
    def is_archived(self) -> bool:
        """Check if this event has been archived."""
        return self.archived_at is not None

    @property
    def is_past(self) -> bool:
        """Check if this event's confirmed date has passed."""
        if not self.confirmed_date or self.confirmed_date == "TBD":
            return False
        try:
            event_time = datetime.fromisoformat(self.confirmed_date)
            # Handle timezone-aware datetimes by making utcnow() aware
            if event_time.tzinfo is not None:
                from datetime import timezone
                now = datetime.now(timezone.utc)
            else:
                now = datetime.utcnow()
            return now > event_time
        except ValueError:
            return False

    @property
    def is_recurring(self) -> bool:
        """Check if this is a recurring event."""
        return self.recurrence is not None and self.recurrence.type != RecurrenceType.NONE

DATA_FILE_NAME = "events.json"

# ========== In-Memory Store ==========

def load_events() -> Dict[str, Dict[str, Dict[str, Union[EventState, Any]]]]:
    try:
        raw = read_json(DATA_FILE_NAME)
        for guild_id, guild_data in raw.items():
            events = guild_data.get("events", {})
            raw[guild_id]["events"] = {
                eid: EventState.from_dict(edata) for eid, edata in events.items()
            }
        return raw
    except FileNotFoundError:
        return {}

events_list = load_events()

# ========== Save ==========

def save_events(data: Dict[str, Dict[str, Dict[str, EventState]]]) -> None:
    to_save = {
        gid: {
            "events": {
                eid: e.to_dict() for eid, e in gdata.get("events", {}).items()
            }
        }
        for gid, gdata in data.items()
    }
    write_json_atomic(DATA_FILE_NAME, to_save)

# ========== CRUD ==========

def get_event(guild_id: int, event_name: str) -> Optional[EventState]:
    events_list = load_events()
    return events_list.get(str(guild_id), {}).get("events", {}).get(event_name)

def get_events(guild_id: int, name: Optional[str] = None) -> Dict[str, EventState]:
    events_list = load_events()
    guild_id_str = str(guild_id)
    raw_events = events_list.get(guild_id_str, {}).get("events", {})
    events = {
        name: event if isinstance(event, EventState) else EventState.from_dict(event)
        for name, event in raw_events.items()
    }

    if not name:
        return events

    name_lower = name.lower()
    for event_name in events:
        if event_name.lower() == name_lower:
            return {event_name: events[event_name]}

    return {
        event_name: event
        for event_name, event in events.items()
        if name_lower in event_name.lower() or event_name.lower().startswith(name_lower)
    }

def modify_event(event_state: Union[EventState, dict]) -> None:
    guild_id = str(event_state.guild_id if isinstance(event_state, EventState) else event_state.get("guild_id"))
    event_name = event_state.event_name if isinstance(event_state, EventState) else event_state.get("event_name")

    if guild_id not in events_list:
        events_list[guild_id] = {"events": {}}

    if isinstance(event_state, dict):
        event_state = EventState.from_dict(event_state)

    events_list[guild_id]["events"][event_name] = event_state
    save_events(events_list)

def delete_event(guild_id: str, event_name: str) -> bool:
    try:
        del events_list[str(guild_id)]["events"][event_name]
        save_events(events_list)
        log_event_action("delete", guild_id, event_name)
        return True
    except KeyError as e:
        logger.warning(f"Event not found for deletion: {event_name} in guild {guild_id}")
        return False


def rename_event(guild_id: int, old_name: str, new_name: str) -> Optional[EventState]:
    """
    Renames an event.

    Args:
        guild_id: The Discord guild ID
        old_name: The current event name
        new_name: The new event name

    Returns:
        The renamed EventState object, or None if the old event was not found
        or the new name already exists.
    """
    guild_id_str = str(guild_id)
    # Not using load_events() here to operate on the global events_list
    
    guild_events = events_list.get(guild_id_str, {}).get("events", {})

    # Check if new name already exists
    if new_name.lower() in [name.lower() for name in guild_events.keys()] and new_name.lower() != old_name.lower():
        logger.warning(f"Failed to rename: new event name '{new_name}' already exists in guild {guild_id}")
        return None

    # Find and remove old event
    event_to_rename = None
    
    # Need to iterate over a copy of keys since we are modifying the dict
    for event_name in list(guild_events.keys()):
        if event_name.lower() == old_name.lower():
            event_to_rename = guild_events.pop(event_name)
            break
    
    if not event_to_rename:
        logger.warning(f"Failed to rename: event '{old_name}' not found in guild {guild_id}")
        return None
        
    # Update name and put it back
    event_to_rename.event_name = new_name
    guild_events[new_name] = event_to_rename
    
    events_list[guild_id_str]["events"] = guild_events
    save_events(events_list)
    log_event_action("rename", guild_id_str, old_name, new_name=new_name)
    
    return event_to_rename


def remove_user_from_queue(queue: dict, user_id: str) -> dict:
    return {str(i + 1): v for i, (k, v) in enumerate(
        (item for item in sorted(queue.items(), key=lambda x: int(x[0])) if item[1] != user_id)
    )}

def user_has_any_availability(user_id: str, availability: dict) -> bool:
    for queue in availability.values():
        if user_id in queue.values():
            return True
    return False


# ========== Archiving Functions ==========

def archive_event(guild_id: str, event_name: str) -> bool:
    """
    Archive an event (mark it as past/completed).

    Archived events are kept for history but excluded from active event lists.

    Args:
        guild_id: The Discord guild ID
        event_name: The event name

    Returns:
        True if archived successfully
    """
    event = get_event(int(guild_id), event_name)
    if not event:
        return False

    event.archived_at = datetime.utcnow().isoformat()
    modify_event(event)
    log_event_action("archive", guild_id, event_name)
    return True


def get_active_events(guild_id: int, name: Optional[str] = None) -> Dict[str, EventState]:
    """
    Get only active (non-archived, non-past) events for a guild.

    This filters out:
    - Events that have been explicitly archived
    - Events whose confirmed date has passed

    Args:
        guild_id: The Discord guild ID
        name: Optional event name filter

    Returns:
        Dict of active events
    """
    all_events = get_events(guild_id, name)
    return {
        event_name: event
        for event_name, event in all_events.items()
        if not event.is_archived and not event.is_past
    }


def get_archived_events(guild_id: int) -> Dict[str, EventState]:
    """
    Get archived events for a guild (event history).

    Returns events that have been archived or whose confirmed date has passed.

    Args:
        guild_id: The Discord guild ID

    Returns:
        Dict of archived events
    """
    all_events = get_events(guild_id)
    return {
        event_name: event
        for event_name, event in all_events.items()
        if event.is_archived or event.is_past
    }


def get_past_events(guild_id: int) -> List[EventState]:
    """
    Get events that have passed but not yet been archived.

    Useful for batch archiving and bulletin updates.

    Args:
        guild_id: The Discord guild ID

    Returns:
        List of past events
    """
    all_events = get_events(guild_id)
    return [
        event for event in all_events.values()
        if event.is_past and not event.is_archived
    ]


def archive_past_events(guild_id: int) -> int:
    """
    Archive all past events for a guild.

    Args:
        guild_id: The Discord guild ID

    Returns:
        Number of events archived
    """
    past_events = get_past_events(guild_id)
    archived_count = 0

    for event in past_events:
        if archive_event(str(guild_id), event.event_name):
            archived_count += 1

    if archived_count > 0:
        logger.info(f"Archived {archived_count} past events for guild {guild_id}")

    return archived_count


def get_event_history(guild_id: int, event_name: Optional[str] = None) -> List[EventState]:
    """
    Get event history for a guild (archived events).

    For recurring events, this shows all past occurrences.

    Args:
        guild_id: The Discord guild ID
        event_name: Optional filter by event name (for recurring event history)

    Returns:
        List of archived events, sorted by date (newest first)
    """
    archived = get_archived_events(guild_id)

    if event_name:
        # Filter by event name (exact or partial for recurring event series)
        name_lower = event_name.lower()
        archived = {
            k: v for k, v in archived.items()
            if name_lower in k.lower() or k.lower().startswith(name_lower)
        }

    # Sort by confirmed_date or archived_at, newest first
    def sort_key(event: EventState):
        if event.confirmed_date and event.confirmed_date != "TBD":
            try:
                return datetime.fromisoformat(event.confirmed_date)
            except ValueError:
                pass
        if event.archived_at:
            try:
                return datetime.fromisoformat(event.archived_at)
            except ValueError:
                pass
        return datetime.min

    return sorted(archived.values(), key=sort_key, reverse=True)


def get_recurring_event_history(guild_id: int, parent_event_id: str) -> List[EventState]:
    """
    Get all past occurrences of a recurring event.

    Args:
        guild_id: The Discord guild ID
        parent_event_id: The parent event ID for the recurring series

    Returns:
        List of past occurrences, sorted by date (newest first)
    """
    all_events = get_events(guild_id)
    archived = get_archived_events(guild_id)

    # Combine and filter by parent_event_id
    all_occurrences = []

    for event in list(all_events.values()) + list(archived.values()):
        if event.recurrence and event.recurrence.parent_event_id == parent_event_id:
            all_occurrences.append(event)
        elif event.event_id == parent_event_id:
            all_occurrences.append(event)

    # Sort by confirmed_date, newest first
    def sort_key(event: EventState):
        if event.confirmed_date and event.confirmed_date != "TBD":
            try:
                return datetime.fromisoformat(event.confirmed_date)
            except ValueError:
                pass
        return datetime.min

    return sorted(all_occurrences, key=sort_key, reverse=True)