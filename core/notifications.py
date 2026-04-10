"""
Notification system for Event Bot.

Handles scheduling and sending notifications for:
- Event reminders (configurable time before event)
- Event start notifications
- Event canceled/changed notifications
"""
import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional, Set, Any, Union
import discord

from core.database import execute_one, execute_query, transaction
from core.logging import get_logger, log_user_action

logger = get_logger(__name__)


# =============================================================================
# Notification Types
# =============================================================================

class NotificationType(Enum):
    """Types of notifications the bot can send."""
    EVENT_REMINDER = "event_reminder"       # Reminder before event starts
    EVENT_START = "event_start"             # When event starts
    EVENT_CANCELED = "event_canceled"       # When event is canceled
    EVENT_CHANGED = "event_changed"         # When event details change
    EVENT_CONFIRMED = "event_confirmed"     # When event date is confirmed


# =============================================================================
# Data Models
# =============================================================================

@dataclass
class NotificationPreference:
    """User's notification preferences for an event."""
    user_id: int
    guild_id: int
    event_name: str
    reminder_minutes: int = 60  # Default: 1 hour before
    notify_on_start: bool = True
    notify_on_change: bool = True
    notify_on_cancel: bool = True
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "guild_id": self.guild_id,
            "event_name": self.event_name,
            "reminder_minutes": self.reminder_minutes,
            "notify_on_start": self.notify_on_start,
            "notify_on_change": self.notify_on_change,
            "notify_on_cancel": self.notify_on_cancel,
            "created_at": self.created_at,
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "NotificationPreference":
        return NotificationPreference(
            user_id=data["user_id"],
            guild_id=data["guild_id"],
            event_name=data["event_name"],
            reminder_minutes=data.get("reminder_minutes", 60),
            notify_on_start=data.get("notify_on_start", True),
            notify_on_change=data.get("notify_on_change", True),
            notify_on_cancel=data.get("notify_on_cancel", True),
            created_at=data.get("created_at", datetime.utcnow().isoformat()),
        )


@dataclass
class ScheduledNotification:
    """A notification scheduled to be sent at a specific time."""
    id: str
    notification_type: NotificationType
    user_id: int
    guild_id: int
    event_name: str
    scheduled_time: str  # ISO format
    message: str
    sent: bool = False
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "notification_type": self.notification_type.value,
            "user_id": self.user_id,
            "guild_id": self.guild_id,
            "event_name": self.event_name,
            "scheduled_time": self.scheduled_time,
            "message": self.message,
            "sent": self.sent,
            "created_at": self.created_at,
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "ScheduledNotification":
        return ScheduledNotification(
            id=data["id"],
            notification_type=NotificationType(data["notification_type"]),
            user_id=data["user_id"],
            guild_id=data["guild_id"],
            event_name=data["event_name"],
            scheduled_time=data["scheduled_time"],
            message=data["message"],
            sent=data.get("sent", False),
            created_at=data.get("created_at", datetime.utcnow().isoformat()),
        )


# =============================================================================
# Preference Management (SQLite-backed)
# =============================================================================

def _row_to_pref(row: dict) -> NotificationPreference:
    return NotificationPreference(
        user_id=int(row["user_id"]),
        guild_id=int(row["guild_id"]),
        event_name=row["event_name"],
        reminder_minutes=row.get("reminder_minutes", 60),
        notify_on_start=bool(row.get("notify_on_start", 1)),
        notify_on_change=bool(row.get("notify_on_change", 1)),
        notify_on_cancel=bool(row.get("notify_on_cancel", 1)),
        created_at=row.get("created_at", datetime.utcnow().isoformat()),
    )


def get_user_preferences(user_id: int, guild_id: int) -> Dict[str, NotificationPreference]:
    """Get all notification preferences for a user in a guild."""
    rows = execute_query(
        "SELECT * FROM notification_preferences WHERE user_id = ? AND guild_id = ?",
        (str(user_id), str(guild_id)),
    )
    return {dict(r)["event_name"]: _row_to_pref(dict(r)) for r in rows}


def get_event_preference(user_id: int, guild_id: int, event_name: str) -> Optional[NotificationPreference]:
    """Get a user's notification preference for a specific event."""
    row = execute_one(
        "SELECT * FROM notification_preferences WHERE user_id = ? AND guild_id = ? AND event_name = ?",
        (str(user_id), str(guild_id), event_name),
    )
    return _row_to_pref(dict(row)) if row else None


def set_notification_preference(preference: NotificationPreference) -> None:
    """Set or update a user's notification preference for an event."""
    with transaction() as cursor:
        cursor.execute(
            """
            INSERT INTO notification_preferences
                (user_id, guild_id, event_name, reminder_minutes,
                 notify_on_start, notify_on_change, notify_on_cancel)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, guild_id, event_name) DO UPDATE SET
                reminder_minutes = excluded.reminder_minutes,
                notify_on_start  = excluded.notify_on_start,
                notify_on_change = excluded.notify_on_change,
                notify_on_cancel = excluded.notify_on_cancel,
                updated_at       = datetime('now')
            """,
            (
                str(preference.user_id),
                str(preference.guild_id),
                preference.event_name,
                preference.reminder_minutes,
                int(preference.notify_on_start),
                int(preference.notify_on_change),
                int(preference.notify_on_cancel),
            ),
        )
    log_user_action(
        "set_notification",
        preference.user_id,
        preference.guild_id,
        event_name=preference.event_name,
        reminder_minutes=preference.reminder_minutes,
    )


def remove_notification_preference(user_id: int, guild_id: int, event_name: str) -> bool:
    """Remove a user's notification preference for an event."""
    with transaction() as cursor:
        cursor.execute(
            "DELETE FROM notification_preferences WHERE user_id = ? AND guild_id = ? AND event_name = ?",
            (str(user_id), str(guild_id), event_name),
        )
        return cursor.rowcount > 0


def get_users_to_notify(guild_id: int, event_name: str) -> List[NotificationPreference]:
    """Get all users who want notifications for an event."""
    rows = execute_query(
        "SELECT * FROM notification_preferences WHERE guild_id = ? AND event_name = ?",
        (str(guild_id), event_name),
    )
    return [_row_to_pref(dict(r)) for r in rows]


def migrate_event_notification_preferences(
    guild_id: int,
    old_event_name: str,
    new_event_name: str,
) -> int:
    """Migrate notification preferences when an event is renamed."""
    with transaction() as cursor:
        cursor.execute(
            """
            UPDATE notification_preferences
            SET event_name = ?, updated_at = datetime('now')
            WHERE guild_id = ? AND event_name = ?
            """,
            (new_event_name, str(guild_id), old_event_name),
        )
        count = cursor.rowcount
    if count:
        logger.info(
            f"Migrated {count} notification preferences: "
            f"'{old_event_name}' → '{new_event_name}' in guild {guild_id}"
        )
    return count


# =============================================================================
# Notification Sending
# =============================================================================

async def send_dm_notification(
    client: discord.Client,
    user_id: int,
    message: str,
    embed: Optional[discord.Embed] = None,
    guild_id: Optional[int] = None,
) -> bool:
    """
    Send a DM notification to a user.

    If the DM fails (user has DMs disabled) and guild_id is provided,
    falls back to the guild's configured notification_channel as a mention.

    Returns:
        True if delivered (DM or channel fallback), False if all attempts failed.
    """
    try:
        user = await client.fetch_user(user_id)
        if user:
            await user.send(content=message, embed=embed)
            logger.info(f"Sent DM notification to user {user_id}")
            return True
    except discord.Forbidden:
        logger.warning(f"Cannot send DM to user {user_id} — DMs disabled; trying channel fallback")
    except discord.HTTPException as e:
        logger.error(f"Failed to send DM to user {user_id}: {e}; trying channel fallback")

    # Channel fallback — only if we know which guild to post in
    if guild_id:
        try:
            from core.conf import get_config
            guild_config = get_config(guild_id)
            channel_id = guild_config.notification_channel
            if channel_id:
                channel = client.get_channel(int(channel_id))
                if channel:
                    fallback_msg = f"<@{user_id}> {message}"
                    await channel.send(content=fallback_msg, embed=embed)
                    logger.info(f"Delivered notification for user {user_id} via channel {channel_id}")
                    return True
        except Exception as e:
            logger.error(f"Channel fallback failed for user {user_id} in guild {guild_id}: {e}")

    return False


async def notify_event_reminder(
    client: discord.Client,
    guild_id: int,
    event_name: str,
    event_time: datetime,
    registered_users: List[int]
) -> int:
    """
    Send reminder notifications to all registered users.

    Returns:
        Number of notifications sent successfully
    """
    sent_count = 0
    users_to_notify = get_users_to_notify(guild_id, event_name)

    # Only notify users who are registered for the event
    registered_set = set(registered_users)

    for pref in users_to_notify:
        if pref.user_id in registered_set:
            time_str = f"<t:{int(event_time.timestamp())}:R>"
            message = (
                f"⏰ **Reminder:** Your event **{event_name}** starts {time_str}!\n\n"
                f"Don't forget to check your availability and join when it starts."
            )

            if await send_dm_notification(client, pref.user_id, message, guild_id=guild_id):
                sent_count += 1

    logger.info(f"Sent {sent_count} reminder notifications for event '{event_name}'")
    return sent_count


async def notify_event_start(
    client: discord.Client,
    guild_id: int,
    event_name: str,
    registered_users: List[int]
) -> int:
    """
    Send event start notifications to all registered users.

    Returns:
        Number of notifications sent successfully
    """
    sent_count = 0
    users_to_notify = get_users_to_notify(guild_id, event_name)
    registered_set = set(registered_users)

    for pref in users_to_notify:
        if pref.user_id in registered_set and pref.notify_on_start:
            message = (
                f"🎉 **{event_name}** is starting now!\n\n"
                f"Head over to the server to join in."
            )

            if await send_dm_notification(client, pref.user_id, message, guild_id=guild_id):
                sent_count += 1

    logger.info(f"Sent {sent_count} start notifications for event '{event_name}'")
    return sent_count


async def notify_event_canceled(
    client: discord.Client,
    guild_id: int,
    event_name: str,
    reason: Optional[str] = None
) -> int:
    """
    Send cancellation notifications to all users who wanted notifications.

    Returns:
        Number of notifications sent successfully
    """
    sent_count = 0
    users_to_notify = get_users_to_notify(guild_id, event_name)

    for pref in users_to_notify:
        if pref.notify_on_cancel:
            message = f"❌ **{event_name}** has been canceled."
            if reason:
                message += f"\n\n**Reason:** {reason}"

            if await send_dm_notification(client, pref.user_id, message, guild_id=guild_id):
                sent_count += 1

    # Clean up preferences for this event
    for pref in users_to_notify:
        remove_notification_preference(pref.user_id, guild_id, event_name)

    logger.info(f"Sent {sent_count} cancellation notifications for event '{event_name}'")
    return sent_count


async def notify_event_changed(
    client: discord.Client,
    guild_id: int,
    event_name: str,
    changes: str
) -> int:
    """
    Send change notifications to all users who wanted notifications.

    Returns:
        Number of notifications sent successfully
    """
    sent_count = 0
    users_to_notify = get_users_to_notify(guild_id, event_name)

    for pref in users_to_notify:
        if pref.notify_on_change:
            message = (
                f"📝 **{event_name}** has been updated!\n\n"
                f"**Changes:**\n{changes}"
            )

            if await send_dm_notification(client, pref.user_id, message, guild_id=guild_id):
                sent_count += 1

    logger.info(f"Sent {sent_count} change notifications for event '{event_name}'")
    return sent_count


async def notify_event_confirmed(
    client: discord.Client,
    guild_id: int,
    event_name: str,
    confirmed_time: datetime
) -> int:
    """
    Send confirmation notifications when an event date is finalized.

    Returns:
        Number of notifications sent successfully
    """
    sent_count = 0
    users_to_notify = get_users_to_notify(guild_id, event_name)

    time_str = f"<t:{int(confirmed_time.timestamp())}:F>"

    for pref in users_to_notify:
        message = (
            f"✅ **{event_name}** has been confirmed!\n\n"
            f"**Date & Time:** {time_str}\n\n"
            f"You'll receive a reminder before it starts."
        )

        if await send_dm_notification(client, pref.user_id, message, guild_id=guild_id):
            sent_count += 1

    logger.info(f"Sent {sent_count} confirmation notifications for event '{event_name}'")
    return sent_count


# =============================================================================
# Background Scheduler
# =============================================================================

class NotificationScheduler:
    """
    Background task that checks for and sends scheduled notifications.

    This runs as a background task in the Discord bot.
    """

    def __init__(self, client: discord.Client):
        self.client = client
        self.running = False
        self._task: Optional[asyncio.Task] = None

    def start(self) -> None:
        """Start the notification scheduler."""
        if not self.running:
            self.running = True
            self._task = asyncio.create_task(self._run())
            logger.info("Notification scheduler started")

    def stop(self) -> None:
        """Stop the notification scheduler."""
        self.running = False
        if self._task:
            self._task.cancel()
            logger.info("Notification scheduler stopped")

    async def _run(self) -> None:
        """Main scheduler loop."""
        while self.running:
            try:
                await self._check_and_send_notifications()
            except Exception as e:
                logger.error(f"Error in notification scheduler: {e}", exc_info=e)

            # Check every minute
            await asyncio.sleep(60)

    async def _check_and_send_notifications(self) -> None:
        """Check for pending notifications and send them."""
        # Import here to avoid circular imports
        from core import events, bulletins
        from datetime import timezone

        now_naive = datetime.utcnow()
        now_aware = datetime.now(timezone.utc)
        all_events = {}

        # Load all events from SQLite across all guilds
        from core.repositories.events import EventRepository
        all_events_by_guild = EventRepository.get_all_events()

        # Archive past events and update their bulletins (runs every check)
        for guild_id_str, guild_events in all_events_by_guild.items():
            guild_id = int(guild_id_str)
            for event in guild_events.values():
                if event.is_past and not event.is_archived:
                    await bulletins.mark_bulletin_as_past(self.client, event)
                    events.archive_event(guild_id_str, event.event_name)

        # Re-load all events for notification checks (archive_event may have mutated state)
        all_events_by_guild = EventRepository.get_all_events()
        for guild_id_str, guild_events in all_events_by_guild.items():
            for event_name, event in guild_events.items():
                all_events[f"{guild_id_str}:{event_name}"] = event

        # Check each event for notifications to send
        for key, event in all_events.items():
            guild_id = int(event.guild_id)

            # Skip events without confirmed dates
            if not event.confirmed_date or event.confirmed_date == "TBD":
                continue

            # Parse confirmed date (assuming ISO format)
            try:
                event_time = datetime.fromisoformat(event.confirmed_date)
            except ValueError:
                continue

            # Use timezone-aware or naive now based on event_time
            now = now_aware if event_time.tzinfo is not None else now_naive

            # Get users who want notifications
            users = get_users_to_notify(guild_id, event.event_name)

            for pref in users:
                # Check if we should send a reminder
                reminder_time = event_time - timedelta(minutes=pref.reminder_minutes)

                # If reminder time is within the last minute, send it
                if reminder_time <= now < reminder_time + timedelta(minutes=1):
                    await notify_event_reminder(
                        self.client,
                        guild_id,
                        event.event_name,
                        event_time,
                        [int(uid) for uid in event.rsvp]
                    )

                # If event is starting now (within last minute), send start notification
                if event_time <= now < event_time + timedelta(minutes=1):
                    await notify_event_start(
                        self.client,
                        guild_id,
                        event.event_name,
                        [int(uid) for uid in event.rsvp]
                    )


# Global scheduler instance (initialized when bot starts)
_scheduler: Optional[NotificationScheduler] = None


def init_scheduler(client: discord.Client) -> NotificationScheduler:
    """Initialize and start the notification scheduler."""
    global _scheduler
    _scheduler = NotificationScheduler(client)
    _scheduler.start()
    return _scheduler


def get_scheduler() -> Optional[NotificationScheduler]:
    """Get the notification scheduler instance."""
    return _scheduler
