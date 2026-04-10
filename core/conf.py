"""
Guild configuration — backed by SQLite (guild_configs table).

Replaces the old guild_config.json flat-file approach.
All reads/writes hit the DB directly; no in-memory cache needed because
the bot's async single-process nature means SQLite WAL handles concurrency.
"""
import json
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Union

from core.database import execute_one, execute_query, transaction
from core.logging import get_logger

logger = get_logger(__name__)


# ========== Config State Model ==========

@dataclass
class ServerConfigState:
    guild_id: str
    admin_roles: List[int] = field(default_factory=list)
    event_organizer_roles: List[int] = field(default_factory=list)
    event_attendee_roles: List[int] = field(default_factory=list)
    bulletin_channel: str = ""

    # Toggleable section settings
    roles_and_permissions_settings_enabled: bool = True
    bulletin_settings_enabled: bool = False
    display_settings_enabled: bool = True

    # Notification settings
    notifications_enabled: bool = True
    default_reminder_minutes: int = 60
    notification_channel: Optional[str] = None

    # Display settings
    use_24hr_time: bool = False

    # Bulletin settings
    bulletin_use_threads: bool = True

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
        if self.notifications_enabled is None:
            self.notifications_enabled = True
        if self.use_24hr_time is None:
            self.use_24hr_time = False
        if self.bulletin_use_threads is None:
            self.bulletin_use_threads = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "guild_id": self.guild_id,
            "admin_roles": self.admin_roles,
            "event_organizer_roles": self.event_organizer_roles,
            "event_attendee_roles": self.event_attendee_roles,
            "bulletin_channel": self.bulletin_channel,
            "roles_and_permissions_settings_enabled": self.roles_and_permissions_settings_enabled,
            "bulletin_settings_enabled": self.bulletin_settings_enabled,
            "display_settings_enabled": self.display_settings_enabled,
            "notifications_enabled": self.notifications_enabled,
            "default_reminder_minutes": self.default_reminder_minutes,
            "notification_channel": self.notification_channel,
            "use_24hr_time": self.use_24hr_time,
            "bulletin_use_threads": self.bulletin_use_threads,
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
            display_settings_enabled=data.get("display_settings_enabled", True),
            notifications_enabled=data.get("notifications_enabled", True),
            default_reminder_minutes=data.get("default_reminder_minutes", 60),
            notification_channel=data.get("notification_channel", None),
            use_24hr_time=data.get("use_24hr_time", False),
            bulletin_use_threads=data.get("bulletin_use_threads", True),
        )


# ========== SQLite helpers ==========

def _row_to_config(row: dict) -> ServerConfigState:
    return ServerConfigState(
        guild_id=row["guild_id"],
        admin_roles=json.loads(row.get("admin_roles") or "[]"),
        event_organizer_roles=json.loads(row.get("event_organizer_roles") or "[]"),
        event_attendee_roles=json.loads(row.get("event_attendee_roles") or "[]"),
        bulletin_channel=row.get("bulletin_channel"),
        roles_and_permissions_settings_enabled=bool(row.get("roles_and_permissions_settings_enabled", 1)),
        bulletin_settings_enabled=bool(row.get("bulletin_settings_enabled", 0)),
        display_settings_enabled=bool(row.get("display_settings_enabled", 1)),
        notifications_enabled=bool(row.get("notifications_enabled", 1)),
        default_reminder_minutes=row.get("default_reminder_minutes", 60),
        notification_channel=row.get("notification_channel"),
        use_24hr_time=bool(row.get("use_24hr_time", 0)),
        bulletin_use_threads=bool(row.get("bulletin_use_threads", 1)),
    )


# ========== CRUD ==========

def get_config(guild_id: int) -> ServerConfigState:
    gid = str(guild_id)
    row = execute_one("SELECT * FROM guild_configs WHERE guild_id = ?", (gid,))
    if row:
        return _row_to_config(dict(row))
    # First access — create a default row and return it
    default = ServerConfigState(guild_id=gid)
    modify_config(default)
    return default


def modify_config(config: Union[ServerConfigState, Dict[str, Any]]) -> None:
    if isinstance(config, dict):
        config = ServerConfigState.from_dict(config)

    gid = str(config.guild_id)
    with transaction() as cursor:
        cursor.execute(
            """
            INSERT INTO guild_configs (
                guild_id, admin_roles, event_organizer_roles, event_attendee_roles,
                bulletin_channel, roles_and_permissions_settings_enabled,
                bulletin_settings_enabled, display_settings_enabled,
                notifications_enabled, default_reminder_minutes, notification_channel,
                use_24hr_time, bulletin_use_threads, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(guild_id) DO UPDATE SET
                admin_roles = excluded.admin_roles,
                event_organizer_roles = excluded.event_organizer_roles,
                event_attendee_roles = excluded.event_attendee_roles,
                bulletin_channel = excluded.bulletin_channel,
                roles_and_permissions_settings_enabled = excluded.roles_and_permissions_settings_enabled,
                bulletin_settings_enabled = excluded.bulletin_settings_enabled,
                display_settings_enabled = excluded.display_settings_enabled,
                notifications_enabled = excluded.notifications_enabled,
                default_reminder_minutes = excluded.default_reminder_minutes,
                notification_channel = excluded.notification_channel,
                use_24hr_time = excluded.use_24hr_time,
                bulletin_use_threads = excluded.bulletin_use_threads,
                updated_at = datetime('now')
            """,
            (
                gid,
                json.dumps(config.admin_roles),
                json.dumps(config.event_organizer_roles),
                json.dumps(config.event_attendee_roles),
                config.bulletin_channel,
                int(config.roles_and_permissions_settings_enabled),
                int(config.bulletin_settings_enabled),
                int(config.display_settings_enabled),
                int(config.notifications_enabled),
                config.default_reminder_minutes,
                config.notification_channel,
                int(config.use_24hr_time),
                int(config.bulletin_use_threads),
            ),
        )


def delete_config(guild_id: Union[str, int]) -> bool:
    gid = str(guild_id)
    with transaction() as cursor:
        cursor.execute("DELETE FROM guild_configs WHERE guild_id = ?", (gid,))
        return cursor.rowcount > 0
