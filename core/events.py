
from typing import Dict, Optional, Union, Any
from core.storage import read_json, write_json_atomic
from dataclasses import dataclass, field
from typing import Set, Dict, Any, Optional, Union

# ========== Event State Model ==========
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
    return events_list.get(str(guild_id), {}).get("events", {}).get(event_name)

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
        return True
    except KeyError as e:
        print(f"[delete_event] Event not found: {e}")
        return False
