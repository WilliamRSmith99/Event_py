import json
import shutil
import pytz
from pathlib import Path
from dataclasses import dataclass, field
from typing import Set, Dict, Any, Optional, Union
from datetime import datetime

# ========== Event State Model ==========

user_event_data = {}  # Global memory store (temporary runtime cache)


@dataclass
class EventState:
    guild_id: str
    event_name: str
    description: str
    organizer: str
    organizer_cname: str
    confirmed_date: str  # Format: MM/DD/YY
    rsvp: Set[str] = field(default_factory=set)
    slots: Set[str] = field(default_factory=set)
    availability: Dict[str, Dict[str, Set[str]]] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "guild_id": self.guild_id,
            "event_name": self.event_name,
            "description": self.description,
            "organizer": self.organizer,
            "organizer_cname": self.organizer_cname,
            "confirmed_date": self.confirmed_date,
            "rsvp": list(self.rsvp),
            "slots": list(self.slots),
            "availability": {
                date: {hour: list(users) for hour, users in hours.items()}
                for date, hours in self.availability.items()
            },
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "EventState":
        return EventState(
            guild_id=data["guild_id"],
            event_name=data["event_name"],
            description=data["description"],
            organizer=data["organizer"],
            organizer_cname=data["organizer_cname"],
            confirmed_date=data["confirmed_date"],
            rsvp=set(data.get("rsvp", [])),
            slots=set(data.get("slots", [])),
            availability={
                date: {hour: set(users) for hour, users in hours.items()}
                for date, hours in data.get("availability", {}).items()
            },
        )

# ========== File Setup & Persistent I/O ==========

DATA_FILE = Path("database/EVENTS.json")


def load_events() -> Dict[str, Dict[str, Dict[str, Union[EventState, Any]]]]:
    if DATA_FILE.exists():
        with open(DATA_FILE, "r") as f:
            raw = json.load(f)
            for guild_id, guild_data in raw.items():
                events = guild_data.get("events", {})
                raw[guild_id]["events"] = {
                    eid: EventState.from_dict(edata) for eid, edata in events.items()
                }
            return raw
    return {}


def save_events(data: Dict[str, Dict[str, Dict[str, EventState]]]) -> None:
    to_save = {
        gid: {
            "events": {
                eid: e.to_dict() for eid, e in gdata.get("events", {}).items()
            }
        }
        for gid, gdata in data.items()
    }

    temp_file = DATA_FILE.with_suffix(".tmp")
    with open(temp_file, "w") as f:
        json.dump(to_save, f, indent=4)

    shutil.move(temp_file, DATA_FILE)

# ========== In-Memory Store ==========

events_list = load_events()

# ========== Event Management Helpers ==========

def delete_event(guild_id: str, event_name: str) -> bool:
    try:
        del events_list[str(guild_id)]["events"][event_name]
        save_events(events_list)
        return True
    except KeyError as e:
        print(f"[delete_event] Event not found: {e}")
        return False


def modify_event(event_state: Union[EventState, dict]) -> None:
    guild_id = event_state.guild_id if isinstance(event_state, EventState) else event_state.get("guild_id")
    event_name = event_state.event_name if isinstance(event_state, EventState) else event_state.get("event_name")

    if guild_id not in events_list:
        events_list[guild_id] = {"events": {}}

    if isinstance(event_state, dict):
        event_state = EventState.from_dict(event_state)

    if isinstance(event_state, EventState):
        events_list[guild_id]["events"][event_name] = event_state
        save_events(events_list)
    else:
        print(f"[modify_event] Invalid event data type for: {event_name}")


def get_event(guild_id: int, event_name: str) -> Optional[EventState]:
    event_data = events_list.get(str(guild_id), {}).get("events", {}).get(str(event_name))
    if event_data is None:
        return None
    return event_data if isinstance(event_data, EventState) else EventState.from_dict(event_data)


def get_events(guild_id: int, name: Optional[str] = None) -> Dict[str, EventState]:
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

    matches = {
        event_name: event
        for event_name, event in events.items()
        if name_lower in event_name.lower() or event_name.lower().startswith(name_lower)
    }

    return matches

# ========== Time Conversion Utilities ==========

def to_utc_isoformat(datetime_str: str, user_timezone: str) -> str:
    """
    Convert a local user time string to UTC ISO format.
    """
    local_tz = pytz.timezone(user_timezone)
    naive = datetime.strptime(datetime_str, "%A, %m/%d/%y at %I%p")
    localized = local_tz.localize(naive)
    return localized.astimezone(pytz.utc).isoformat()


def from_utc_to_local(utc_date_str: str, user_timezone: str) -> str:
    """
    Convert a UTC time string to a user's local time in ISO format.
    """
    try:
        naive_utc = datetime.strptime(utc_date_str, "%A, %m/%d/%y at %I%p")
        user_tz = pytz.timezone(user_timezone)
        normalized = pytz.utc.localize(naive_utc)
        return normalized.astimezone(user_tz).isoformat()
    except Exception as e:
        print(f"[from_utc_to_local] Error: {e}")
        return utc_date_str


def parse_utc_availability_key(utc_date_str: str, utc_hour_str: str) -> Optional[datetime]:
    """
    Parse UTC date and hour strings into a timezone-aware UTC datetime.
    """
    try:
        combined = f"{utc_date_str} {utc_hour_str.upper()}"
        naive = datetime.strptime(combined, "%A, %m/%d/%y %I%p")
        return pytz.utc.localize(naive)
    except ValueError as e:
        print(f"[parse_utc_availability_key] Invalid datetime: {combined} - {e}")
        return None
