from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Union
from core.storage import read_json, write_json_atomic

CONFIG_FILE_NAME = "guild_config.json"

# ========== Config State Model ==========

@dataclass
class ServerConfigState:
    guild_id: str
    admin_roles: List[int] = field(default_factory=list)
    event_organizer_roles: List[int] = field(default_factory=list)
    event_attendee_roles: List[int] = field(default_factory=list)
    bulletin_channel: List[int] = field(default_factory=list)

    # Toggleable section settings
    roles_and_permissions_settings_enabled: bool = True
    bulletin_settings_enabled: bool = False
    display_settings_enabled: bool = True

    def __post_init__(self):
        self.admin_roles = self.admin_roles or []
        self.event_organizer_roles = self.event_organizer_roles or []
        self.event_attendee_roles = self.event_attendee_roles or []
        self.bulletin_channel = self.bulletin_channel or None
        if self.roles_and_permissions_settings_enabled is None:
            self.roles_and_permissions_settings_enabled = True
        if self.bulletin_settings_enabled is None:
            self.bulletin_settings_enabled = False
        if self.display_settings_enabled is None:
            self.display_settings_enabled = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "guild_id": self.guild_id,
            "admin_roles": self.admin_roles,
            "event_organizer_roles": self.event_organizer_roles,
            "event_attendee_roles": self.event_attendee_roles,
            "bulletin_channel": self.bulletin_channel,
            "roles_and_permissions_settings_enabled": self.roles_and_permissions_settings_enabled,
            "bulletin_settings_enabled": self.bulletin_settings_enabled,
            "display_settings_enabled": self.display_settings_enabled
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "ServerConfigState":
        return ServerConfigState(
            guild_id=data["guild_id"],
            admin_roles=data.get("admin_roles", []),
            event_organizer_roles=data.get("event_organizer_roles", []),
            event_attendee_roles=data.get("event_attendee_roles", []),
            bulletin_channel=data.get("bulletin_channel", None),
            roles_and_permissions_settings_enabled=data.get("roles_and_permissions_settings_enabled", True),
            bulletin_settings_enabled=data.get("bulletin_settings_enabled", False),
            display_settings_enabled=data.get("display_settings_enabled", True)
        )


# ========== In-Memory Store ==========

def load_all_configs() -> Dict[str, Dict[str, Union[ServerConfigState, Any]]]:
    try:
        raw = read_json(CONFIG_FILE_NAME)
        return {
            gid: {
                "config": ServerConfigState.from_dict(guild_data["config"])
            }
            for gid, guild_data in raw.get("servers", {}).items()
        }
    except FileNotFoundError:
        return {}

config_list: Dict[str, Dict[str, ServerConfigState]] = load_all_configs()

# ========== Save ==========

def save_all_configs(data: Dict[str, Dict[str, ServerConfigState]]) -> None:
    to_save = {
        "servers": {
            gid: {
                "config": config.to_dict()
            }
            for gid, guild_data in data.items()
            for config in guild_data.values()
        }
    }
    write_json_atomic(CONFIG_FILE_NAME, to_save)

# ========== CRUD ==========

def get_config(guild_id: int) -> ServerConfigState:
    gid = str(guild_id)
    if gid not in config_list or "config" not in config_list[gid]:
        config = ServerConfigState(guild_id=gid)
        config_list[gid] = {"config": config}
        save_all_configs(config_list)
    return config_list[gid]["config"]

def modify_config(config: Union[ServerConfigState, Dict[str, Any]]) -> None:
    guild_id = str(config.guild_id if isinstance(config, ServerConfigState) else config.get("guild_id"))

    if isinstance(config, dict):
        config = ServerConfigState.from_dict(config)

    if guild_id not in config_list:
        config_list[guild_id] = {}

    config_list[guild_id]["config"] = config
    save_all_configs(config_list)

def delete_config(guild_id: Union[str, int]) -> bool:
    try:
        del config_list[str(guild_id)]
        save_all_configs(config_list)
        return True
    except KeyError:
        return False
