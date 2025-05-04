import pytz, json, shutil
from pathlib import Path
from dataclasses import dataclass, field
from typing import Set, Dict, Any, List
from datetime import datetime

# =========================
# EventState Data Structure
# =========================
user_event_data = {}

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
        # Convert internal sets to lists for JSON serialization
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

# =========================
# File Setup & I/O Helpers
# =========================

DATA_FILE = Path("database/EVENTS.json")

def load_events() -> Dict[str, Dict[str, Dict[str, Any]]]:
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

def save_events(data):
    to_save = {
        gid: {
            "events": {
                eid: e.to_dict() for eid, e in gdata.get("events", {}).items()
            }
        }
        for gid, gdata in data.items()
    }

    # Write to a temporary file first
    temp_file = DATA_FILE.with_suffix(".tmp")
    with open(temp_file, "w") as f:
        json.dump(to_save, f, indent=4)

    # Atomically replace the original file
    shutil.move(temp_file, DATA_FILE)
# =========================
# Global In-Memory Store
# =========================

events_list = load_events()

# =========================
# Event Management Helpers
# =========================

def delete_event(guild_id: str, event_name: str) -> bool:
    try:
        del events_list[str(guild_id)]["events"][event_name]
        save_events(events_list)
        return True
    except KeyError as e:
        print(e)
        return False

def modify_event(event_state: EventState | dict) -> None:
    guild_id_str = event_state.guild_id
    event_name_str = event_state.event_name

    if guild_id_str not in events_list:
        events_list[guild_id_str] = {"events": {}}

    # Ensure the event is an EventState instance, convert if it's not
    if isinstance(event_state, EventState):
        events_list[guild_id_str]["events"][event_name_str] = event_state
    elif isinstance(event_state, dict):
        # If it's a dict, convert it to an EventState instance
        event_state_obj = EventState.from_dict(event_state)
        events_list[guild_id_str]["events"][event_name_str] = event_state_obj
    else:
        # Handle error case if it's neither a dict nor an EventState instance
        print(f"Error: The event {event_name_str} is neither an EventState nor dict")

    save_events(events_list)
    
    
def get_event(guild_id: int, event_name: str) -> EventState | None:
    event_data = events_list.get(str(guild_id), {}).get("events", {}).get(str(event_name))
    if event_data is None:
        return None
    if isinstance(event_data, EventState):
        return event_data
    return EventState.from_dict(event_data)

def get_all_events(guild_id: int) -> Dict[str, EventState]:
    guild_id_str = str(guild_id)
    raw_events = events_list.get(guild_id_str, {}).get("events", {})

    return {
        event_name: (
            event_data if isinstance(event_data, EventState)
            else EventState.from_dict(event_data)
        )
        for event_name, event_data in raw_events.items()
    }

def resolve_event_names(guild_id: str, partial_id: str) -> list[str]:
    """Return a list of event names that match the partial ID by prefix or substring."""
    guild_events = events_list.get(str(guild_id))
    if not guild_events:
        return []

    events = guild_events.get("events")
    if not events:
        return []

    partial_id_lower = partial_id.lower()
    event_ids = [eid for eid in events]

    # Normalize to lowercase for comparison
    startswith_matches = [eid for eid in event_ids if eid.lower().startswith(partial_id_lower)]
    if startswith_matches:
        return startswith_matches

    contains_matches = [eid for eid in event_ids if partial_id_lower in eid.lower()]
    return contains_matches


def to_utc_isoformat(datetime_str: str, user_timezone: str) -> str:
    """
    Convert a time string like 'Tuesday, 12/07/99 at 5PM' in user's timezone to UTC ISO 8601.
    """
    local_tz = pytz.timezone(user_timezone)
    naive = datetime.strptime(datetime_str, "%A, %m/%d/%y at %I%p")
    localized = local_tz.localize(naive)
    return localized.astimezone(pytz.utc).isoformat()

def from_utc_to_local(utc_date_str: str, user_timezone: str) -> str:
    """
    Convert a time string like 'Tuesday, 12/07/99 at 5PM' in UTC ISO 8601 to user's local timezone.
    """
    try:
        naive_utc = datetime.strptime(utc_date_str, "%A, %m/%d/%y at %I%p")
        user_tz = pytz.timezone(user_timezone)
        normalized = pytz.utc.localize(naive_utc)
        return normalized.astimezone(user_tz).isoformat()

    except Exception as e:
        print(f"⚠️ Error localizing date '{utc_date_str}': {e}")
        return utc_date_str  # fallback
    
def parse_utc_availability_key(utc_date_str: str, utc_hour_str: str) -> datetime:
    """
    Parses the stored UTC date ('Day, MM/DD/YY') and hour ('HHAM/PM') strings
    into a timezone-aware UTC datetime object.
    """
    try:
        # Combine and parse the naive datetime string
        # Example: "Thursday, 04/24/25" + " " + "02AM" -> "Thursday, 04/24/25 02AM"
        naive_dt_str = f"{utc_date_str} {utc_hour_str.upper()}"
        naive_dt = datetime.strptime(naive_dt_str, "%A, %m/%d/%y %I%p")

        # Localize the naive datetime as UTC
        utc_dt = pytz.utc.localize(naive_dt)
        return utc_dt
    except ValueError as e:
        print(f"Error parsing UTC availability key: {utc_date_str} {utc_hour_str} - {e}")
        return None # Or raise an error