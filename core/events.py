from core.logging import get_logger, log_event_action
from dataclasses import dataclass, field
from datetime import datetime, timedelta
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
    organizer: int  # Discord user ID
    organizer_cname: str
    confirmed_date: str
    event_id: Optional[str] = field(default_factory=lambda: str(uuid.uuid4()))
    bulletin_channel_id: Optional[int] = None
    bulletin_message_id: Optional[int] = None
    bulletin_thread_id: Optional[int] = None
    rsvp: List[int] = field(default_factory=list)  # List of Discord user IDs
    slots: list[str] = field(default_factory=list)
    availability: Dict[str, Dict[str, int]] = field(default_factory=dict)  # {slot: {position: user_id}}
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
        if self.recurrence:
            result["recurrence"] = self.recurrence.to_dict()
        return result

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "EventState":
        recurrence = None
        if "recurrence" in data and data["recurrence"]:
            recurrence = RecurrenceConfig.from_dict(data["recurrence"])

        organizer = data["organizer"]
        if isinstance(organizer, str):
            organizer = int(organizer)

        rsvp_raw = data.get("rsvp", [])
        rsvp = [int(uid) if isinstance(uid, str) else uid for uid in rsvp_raw]

        availability_raw = data.get("availability", {})
        availability = {}
        for slot, users in availability_raw.items():
            availability[slot] = {
                pos: (int(uid) if isinstance(uid, str) else uid)
                for pos, uid in users.items()
            }

        return EventState(
            guild_id=data["guild_id"],
            event_name=data["event_name"],
            event_id=data.get("event_id", str(uuid.uuid4())),
            max_attendees=data["max_attendees"],
            organizer=organizer,
            organizer_cname=data["organizer_cname"],
            confirmed_date=data["confirmed_date"],
            bulletin_channel_id=data.get("bulletin_channel_id"),
            bulletin_message_id=data.get("bulletin_message_id"),
            bulletin_thread_id=data.get("bulletin_thread_id"),
            rsvp=rsvp,
            slots=data.get("slots", []),
            availability=availability,
            waitlist=data.get("waitlist", {}),
            availability_to_message_map=data.get("availability_to_message_map", {}),
            recurrence=recurrence,
            archived_at=data.get("archived_at"),
            created_at=data.get("created_at"),
        )

    @property
    def is_archived(self) -> bool:
        return self.archived_at is not None

    @property
    def is_past(self) -> bool:
        if not self.confirmed_date or self.confirmed_date == "TBD":
            return False
        try:
            event_time = datetime.fromisoformat(self.confirmed_date)
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
        return self.recurrence is not None and self.recurrence.type != RecurrenceType.NONE


# ========== SQLite-backed CRUD ==========

_repo = None


def _get_repo():
    """Lazy-load EventRepository to avoid circular imports."""
    global _repo
    if _repo is None:
        from core.repositories.events import EventRepository
        _repo = EventRepository
    return _repo


def get_event(guild_id: int, event_name: str) -> Optional[EventState]:
    return _get_repo().get_event(guild_id, event_name)


def get_events(guild_id: int, name: Optional[str] = None) -> Dict[str, EventState]:
    return _get_repo().get_events(guild_id, name_filter=name)


def modify_event(event_state: Union[EventState, dict]) -> None:
    """Upsert an event to SQLite."""
    repo = _get_repo()
    if isinstance(event_state, dict):
        event_state = EventState.from_dict(event_state)

    existing = None
    if event_state.event_id:
        existing = repo.get_event_by_id(event_state.event_id)

    if existing:
        repo.update_event(event_state)
    else:
        repo.create_event(event_state)


def delete_event(guild_id: str, event_name: str) -> bool:
    result = _get_repo().delete_event(int(guild_id), event_name)
    if result:
        log_event_action("delete", guild_id, event_name)
    else:
        logger.warning(f"Event not found for deletion: {event_name} in guild {guild_id}")
    return result


def rename_event(guild_id: int, old_name: str, new_name: str) -> Optional[EventState]:
    """Rename an event. Returns the updated EventState or None on failure."""
    repo = _get_repo()
    guild_id_str = str(guild_id)

    # Check new name doesn't already exist (case-insensitive)
    existing = repo.get_events(guild_id, name_filter=new_name)
    for name in existing.keys():
        if name.lower() == new_name.lower() and name.lower() != old_name.lower():
            logger.warning(f"Failed to rename: '{new_name}' already exists in guild {guild_id}")
            return None

    # Find the event to rename
    candidates = repo.get_events(guild_id, name_filter=old_name)
    event_to_rename = None
    for name, event in candidates.items():
        if name.lower() == old_name.lower():
            event_to_rename = event
            break

    if not event_to_rename:
        logger.warning(f"Failed to rename: '{old_name}' not found in guild {guild_id}")
        return None

    event_to_rename.event_name = new_name
    repo.update_event(event_to_rename)
    log_event_action("rename", guild_id_str, old_name, new_name=new_name)
    return event_to_rename


# ========== Utility Functions ==========

def remove_user_from_queue(queue: dict, user_id: int) -> dict:
    """Remove a user from a queue and reorder positions."""
    return {str(i + 1): v for i, (k, v) in enumerate(
        (item for item in sorted(queue.items(), key=lambda x: int(x[0])) if item[1] != user_id)
    )}


def user_has_any_availability(user_id: int, availability: dict) -> bool:
    """Check if a user has any availability in any slot."""
    for queue in availability.values():
        if user_id in queue.values():
            return True
    return False


# ========== Archiving Functions ==========

def archive_event(guild_id: str, event_name: str) -> bool:
    event = get_event(int(guild_id), event_name)
    if not event:
        return False
    event.archived_at = datetime.utcnow().isoformat()
    modify_event(event)
    log_event_action("archive", guild_id, event_name)
    return True


def get_active_events(guild_id: int, name: Optional[str] = None) -> Dict[str, EventState]:
    all_events = get_events(guild_id, name)
    return {
        event_name: event
        for event_name, event in all_events.items()
        if not event.is_archived and not event.is_past
    }


def get_archived_events(guild_id: int) -> Dict[str, EventState]:
    all_events = get_events(guild_id)
    return {
        event_name: event
        for event_name, event in all_events.items()
        if event.is_archived or event.is_past
    }


def get_past_events(guild_id: int) -> List[EventState]:
    all_events = get_events(guild_id)
    return [
        event for event in all_events.values()
        if event.is_past and not event.is_archived
    ]


def archive_past_events(guild_id: int) -> int:
    past_events = get_past_events(guild_id)
    archived_count = 0
    for event in past_events:
        if archive_event(str(guild_id), event.event_name):
            archived_count += 1
    if archived_count > 0:
        logger.info(f"Archived {archived_count} past events for guild {guild_id}")
    return archived_count


def get_event_history(guild_id: int, event_name: Optional[str] = None) -> List[EventState]:
    archived = get_archived_events(guild_id)

    if event_name:
        name_lower = event_name.lower()
        archived = {
            k: v for k, v in archived.items()
            if name_lower in k.lower() or k.lower().startswith(name_lower)
        }

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


def generate_recurring_instances(parent: EventState, window_days: int = 28) -> int:
    """
    Create child event instances for a recurring parent within the next window_days.

    Only creates instances that don't already exist (idempotent).
    Returns the number of new instances created.
    """
    if not parent.is_recurring:
        return 0
    if not parent.confirmed_date or parent.confirmed_date == "TBD":
        return 0

    import calendar as _calendar
    from datetime import timezone as _tz

    try:
        parent_dt = datetime.fromisoformat(parent.confirmed_date)
        if parent_dt.tzinfo is None:
            parent_dt = parent_dt.replace(tzinfo=_tz.utc)

        now = datetime.now(_tz.utc)
        window_end = now + timedelta(days=window_days)
        recurrence = parent.recurrence

        def _next_monthly(dt: datetime, interval: int) -> datetime:
            month = dt.month + interval
            year = dt.year + (month - 1) // 12
            month = ((month - 1) % 12) + 1
            last_day = _calendar.monthrange(year, month)[1]
            return dt.replace(year=year, month=month, day=min(dt.day, last_day))

        if recurrence.type == RecurrenceType.DAILY:
            delta: Optional[timedelta] = timedelta(days=recurrence.interval or 1)
        elif recurrence.type == RecurrenceType.WEEKLY:
            delta = timedelta(weeks=recurrence.interval or 1)
        elif recurrence.type == RecurrenceType.BIWEEKLY:
            delta = timedelta(weeks=2 * (recurrence.interval or 1))
        elif recurrence.type == RecurrenceType.MONTHLY:
            delta = None
        else:
            return 0

        # Gather confirmed_dates of existing children to skip duplicates
        repo = _get_repo()
        existing_children = repo.get_events_by_parent(int(parent.guild_id), parent.event_id)
        existing_dates = {c.confirmed_date for c in existing_children}

        # Advance to first instance that falls within the window
        current_dt = parent_dt
        occurrence_num = 0
        while current_dt < now:
            if delta:
                current_dt += delta
            else:
                current_dt = _next_monthly(current_dt, recurrence.interval or 1)
            occurrence_num += 1

        created = 0
        while current_dt <= window_end:
            if recurrence.end_date:
                end_dt = datetime.fromisoformat(recurrence.end_date)
                if end_dt.tzinfo is None:
                    end_dt = end_dt.replace(tzinfo=_tz.utc)
                if current_dt > end_dt:
                    break
            if recurrence.occurrences and occurrence_num >= recurrence.occurrences:
                break

            iso_dt = current_dt.isoformat()
            if iso_dt not in existing_dates:
                date_label = current_dt.strftime("%b %d")
                child = EventState(
                    guild_id=parent.guild_id,
                    event_name=f"{parent.event_name} - {date_label}",
                    max_attendees=parent.max_attendees,
                    organizer=parent.organizer,
                    organizer_cname=parent.organizer_cname,
                    confirmed_date=iso_dt,
                    availability={iso_dt: {}},
                    recurrence=RecurrenceConfig(
                        type=recurrence.type,
                        interval=recurrence.interval,
                        end_date=recurrence.end_date,
                        occurrences=recurrence.occurrences,
                        parent_event_id=parent.event_id,
                    ),
                )
                repo.create_event(child)
                existing_dates.add(iso_dt)
                created += 1
                logger.info(f"Created recurring instance '{child.event_name}'")

            occurrence_num += 1
            if delta:
                current_dt += delta
            else:
                current_dt = _next_monthly(current_dt, recurrence.interval or 1)

        return created

    except Exception as e:
        logger.error(f"Error generating recurring instances for '{parent.event_name}': {e}", exc_info=True)
        return 0


def get_recurring_event_history(guild_id: int, parent_event_id: str) -> List[EventState]:
    all_events = get_events(guild_id)
    archived = get_archived_events(guild_id)

    all_occurrences = []
    for event in list(all_events.values()) + list(archived.values()):
        if event.recurrence and event.recurrence.parent_event_id == parent_event_id:
            all_occurrences.append(event)
        elif event.event_id == parent_event_id:
            all_occurrences.append(event)

    def sort_key(event: EventState):
        if event.confirmed_date and event.confirmed_date != "TBD":
            try:
                return datetime.fromisoformat(event.confirmed_date)
            except ValueError:
                pass
        return datetime.min

    return sorted(all_occurrences, key=sort_key, reverse=True)
