"""
Notification Repository for Event Bot.

Handles all database operations for notification preferences
and scheduled notifications.
"""
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Any

from core.database import (
    get_cursor, transaction, execute_query, execute_one,
    execute_write, execute_insert
)
from core.logging import get_logger
from core.notifications import NotificationPreference, NotificationType, ScheduledNotification

logger = get_logger(__name__)


class NotificationRepository:
    """Repository for notification data operations."""

    # =========================================================================
    # Notification Preferences
    # =========================================================================

    @staticmethod
    def get_preference(
        user_id: int,
        guild_id: int,
        event_name: str
    ) -> Optional[NotificationPreference]:
        """
        Get a user's notification preference for an event.

        Args:
            user_id: Discord user ID
            guild_id: Discord guild ID
            event_name: Name of the event

        Returns:
            NotificationPreference or None
        """
        row = execute_one(
            """
            SELECT * FROM notification_preferences
            WHERE user_id = ? AND guild_id = ? AND event_name = ?
            """,
            (str(user_id), str(guild_id), event_name)
        )

        if row:
            return NotificationRepository._row_to_preference(dict(row))
        return None

    @staticmethod
    def get_user_preferences(
        user_id: int,
        guild_id: int
    ) -> Dict[str, NotificationPreference]:
        """
        Get all notification preferences for a user in a guild.

        Args:
            user_id: Discord user ID
            guild_id: Discord guild ID

        Returns:
            Dict mapping event_name -> NotificationPreference
        """
        rows = execute_query(
            """
            SELECT * FROM notification_preferences
            WHERE user_id = ? AND guild_id = ?
            """,
            (str(user_id), str(guild_id))
        )

        return {
            row["event_name"]: NotificationRepository._row_to_preference(dict(row))
            for row in rows
        }

    @staticmethod
    def get_event_subscribers(
        guild_id: int,
        event_name: str
    ) -> List[NotificationPreference]:
        """
        Get all users who want notifications for an event.

        Args:
            guild_id: Discord guild ID
            event_name: Name of the event

        Returns:
            List of NotificationPreference objects
        """
        rows = execute_query(
            """
            SELECT * FROM notification_preferences
            WHERE guild_id = ? AND event_name = ?
            """,
            (str(guild_id), event_name)
        )

        return [
            NotificationRepository._row_to_preference(dict(row))
            for row in rows
        ]

    @staticmethod
    def set_preference(preference: NotificationPreference) -> bool:
        """
        Set or update a notification preference.

        Args:
            preference: NotificationPreference to save

        Returns:
            True if saved successfully
        """
        try:
            execute_write(
                """
                INSERT INTO notification_preferences (
                    user_id, guild_id, event_name, reminder_minutes,
                    notify_on_start, notify_on_change, notify_on_cancel
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, guild_id, event_name) DO UPDATE SET
                    reminder_minutes = excluded.reminder_minutes,
                    notify_on_start = excluded.notify_on_start,
                    notify_on_change = excluded.notify_on_change,
                    notify_on_cancel = excluded.notify_on_cancel,
                    updated_at = datetime('now')
                """,
                (
                    str(preference.user_id),
                    str(preference.guild_id),
                    preference.event_name,
                    preference.reminder_minutes,
                    1 if preference.notify_on_start else 0,
                    1 if preference.notify_on_change else 0,
                    1 if preference.notify_on_cancel else 0
                )
            )
            logger.debug(
                f"Set notification preference for user {preference.user_id} "
                f"event {preference.event_name}"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to set notification preference: {e}")
            return False

    @staticmethod
    def remove_preference(user_id: int, guild_id: int, event_name: str) -> bool:
        """
        Remove a notification preference.

        Args:
            user_id: Discord user ID
            guild_id: Discord guild ID
            event_name: Name of the event

        Returns:
            True if removed successfully
        """
        try:
            rows_affected = execute_write(
                """
                DELETE FROM notification_preferences
                WHERE user_id = ? AND guild_id = ? AND event_name = ?
                """,
                (str(user_id), str(guild_id), event_name)
            )
            return rows_affected > 0

        except Exception as e:
            logger.error(f"Failed to remove notification preference: {e}")
            return False

    @staticmethod
    def remove_event_preferences(guild_id: int, event_name: str) -> int:
        """
        Remove all notification preferences for an event.

        Args:
            guild_id: Discord guild ID
            event_name: Name of the event

        Returns:
            Number of preferences removed
        """
        try:
            return execute_write(
                """
                DELETE FROM notification_preferences
                WHERE guild_id = ? AND event_name = ?
                """,
                (str(guild_id), event_name)
            )

        except Exception as e:
            logger.error(f"Failed to remove event preferences: {e}")
            return 0

    # =========================================================================
    # Scheduled Notifications
    # =========================================================================

    @staticmethod
    def schedule_notification(
        notification_type: NotificationType,
        user_id: int,
        guild_id: int,
        event_name: str,
        scheduled_time: datetime,
        message: str
    ) -> Optional[str]:
        """
        Schedule a notification to be sent at a specific time.

        Args:
            notification_type: Type of notification
            user_id: Discord user ID
            guild_id: Discord guild ID
            event_name: Name of the event
            scheduled_time: When to send the notification
            message: Message content

        Returns:
            Notification ID if created, None on failure
        """
        try:
            notification_id = str(uuid.uuid4())
            execute_write(
                """
                INSERT INTO scheduled_notifications (
                    id, notification_type, user_id, guild_id, event_name,
                    scheduled_time, message
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    notification_id,
                    notification_type.value,
                    str(user_id),
                    str(guild_id),
                    event_name,
                    scheduled_time.isoformat(),
                    message
                )
            )
            return notification_id

        except Exception as e:
            logger.error(f"Failed to schedule notification: {e}")
            return None

    @staticmethod
    def get_pending_notifications(before: Optional[datetime] = None) -> List[ScheduledNotification]:
        """
        Get all pending (unsent) notifications.

        Args:
            before: Optional cutoff time (defaults to now)

        Returns:
            List of pending ScheduledNotification objects
        """
        if before is None:
            before = datetime.utcnow()

        rows = execute_query(
            """
            SELECT * FROM scheduled_notifications
            WHERE sent = 0 AND scheduled_time <= ?
            ORDER BY scheduled_time ASC
            """,
            (before.isoformat(),)
        )

        return [
            NotificationRepository._row_to_scheduled(dict(row))
            for row in rows
        ]

    @staticmethod
    def mark_notification_sent(notification_id: str) -> bool:
        """
        Mark a notification as sent.

        Args:
            notification_id: ID of the notification

        Returns:
            True if marked successfully
        """
        try:
            execute_write(
                "UPDATE scheduled_notifications SET sent = 1 WHERE id = ?",
                (notification_id,)
            )
            return True

        except Exception as e:
            logger.error(f"Failed to mark notification sent: {e}")
            return False

    @staticmethod
    def delete_notification(notification_id: str) -> bool:
        """
        Delete a scheduled notification.

        Args:
            notification_id: ID of the notification

        Returns:
            True if deleted successfully
        """
        try:
            execute_write(
                "DELETE FROM scheduled_notifications WHERE id = ?",
                (notification_id,)
            )
            return True

        except Exception as e:
            logger.error(f"Failed to delete notification: {e}")
            return False

    @staticmethod
    def delete_event_notifications(guild_id: int, event_name: str) -> int:
        """
        Delete all scheduled notifications for an event.

        Args:
            guild_id: Discord guild ID
            event_name: Name of the event

        Returns:
            Number of notifications deleted
        """
        try:
            return execute_write(
                """
                DELETE FROM scheduled_notifications
                WHERE guild_id = ? AND event_name = ?
                """,
                (str(guild_id), event_name)
            )

        except Exception as e:
            logger.error(f"Failed to delete event notifications: {e}")
            return 0

    @staticmethod
    def cleanup_sent_notifications(older_than_days: int = 7) -> int:
        """
        Clean up old sent notifications.

        Args:
            older_than_days: Delete notifications older than this

        Returns:
            Number of notifications deleted
        """
        try:
            return execute_write(
                """
                DELETE FROM scheduled_notifications
                WHERE sent = 1
                AND created_at < datetime('now', '-' || ? || ' days')
                """,
                (older_than_days,)
            )

        except Exception as e:
            logger.error(f"Failed to cleanup notifications: {e}")
            return 0

    # =========================================================================
    # Helper Methods
    # =========================================================================

    @staticmethod
    def _row_to_preference(row: dict) -> NotificationPreference:
        """Convert a database row to a NotificationPreference object."""
        return NotificationPreference(
            user_id=int(row["user_id"]),
            guild_id=int(row["guild_id"]),
            event_name=row["event_name"],
            reminder_minutes=row.get("reminder_minutes", 60),
            notify_on_start=bool(row.get("notify_on_start", 1)),
            notify_on_change=bool(row.get("notify_on_change", 1)),
            notify_on_cancel=bool(row.get("notify_on_cancel", 1)),
            created_at=row.get("created_at", datetime.utcnow().isoformat())
        )

    @staticmethod
    def _row_to_scheduled(row: dict) -> ScheduledNotification:
        """Convert a database row to a ScheduledNotification object."""
        return ScheduledNotification(
            id=row["id"],
            notification_type=NotificationType(row["notification_type"]),
            user_id=int(row["user_id"]),
            guild_id=int(row["guild_id"]),
            event_name=row["event_name"],
            scheduled_time=row["scheduled_time"],
            message=row["message"],
            sent=bool(row.get("sent", 0)),
            created_at=row.get("created_at", datetime.utcnow().isoformat())
        )
