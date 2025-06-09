from dataclasses import dataclass, field
from typing import Dict, Any, Union
from core.storage import read_json, write_json_atomic

EVENT_BULLETIN_FILE_NAME = "event_bulletin.json"

# ========== Data Model ==========

@dataclass
class BulletinMessageEntry:
    event: str = ""
    msg_head_id: str = ""
    thread_id: str = ""
    thread_messages: Dict[str, Dict[str, str]] = field(default_factory=dict)
    # Structure: {THREAD_MSG_ID: {"options": {emoji: value}}}

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "BulletinMessageEntry":
        return BulletinMessageEntry(
            event=data.get("event", ""),
            msg_head_id=data.get("msg_head_id", ""),
            thread_id=data.get("thread_id", ""),
            thread_messages=data.get("thread_messages", {})
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event": self.event,
            "msg_head_id": self.msg_head_id,
            "thread_id": self.thread_id,
            "thread_messages": self.thread_messages
        }

# ========== In-Memory Store ==========

def load_event_bulletins() -> Dict[str, Dict[str, BulletinMessageEntry]]:
    try:
        raw = read_json(EVENT_BULLETIN_FILE_NAME)
        return {
            guild_id: {
                head_msg_id: BulletinMessageEntry.from_dict(head_data)
                for head_msg_id, head_data in guild_data.items()
            }
            for guild_id, guild_data in raw.items()
        }
    except FileNotFoundError:
        return {}

# ========== Save ==========

def save_event_bulletins(data: Dict[str, Dict[str, BulletinMessageEntry]]) -> None:
    to_save = {
        guild_id: {
            head_msg_id: entry.to_dict()
            for head_msg_id, entry in head_msgs.items()
        }
        for guild_id, head_msgs in data.items()
    }
    write_json_atomic(EVENT_BULLETIN_FILE_NAME, to_save)

# ========== CRUD ==========

def get_event_bulletin(guild_id: Union[str, int]) -> Dict[str, BulletinMessageEntry]:
    event_bulletins = load_event_bulletins()
    gid = str(guild_id)
    if gid not in event_bulletins:
        event_bulletins[gid] = {}
        save_event_bulletins(event_bulletins)
    return event_bulletins[gid]

def modify_event_bulletin(guild_id: Union[str, int], entry: BulletinMessageEntry) -> None:
    head_msg_id = entry.msg_head_id
    event_bulletins = load_event_bulletins()
    gid = str(guild_id)
    if gid not in event_bulletins:
        event_bulletins[gid] = {}
    event_bulletins[gid][head_msg_id] = entry
    save_event_bulletins(event_bulletins)

def delete_event_bulletin(guild_id: Union[str, int], head_msg_id: str) -> bool:
    event_bulletins = load_event_bulletins()
    gid = str(guild_id)
    try:
        del event_bulletins[gid][head_msg_id]
        if not event_bulletins[gid]:
            del event_bulletins[gid]
        save_event_bulletins(event_bulletins)
        return True
    except KeyError:
        return False
