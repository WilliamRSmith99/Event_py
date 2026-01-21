"""
Event Repository for Event Bot.

Handles all database operations for events, including:
- Event CRUD operations
- RSVP management
- Availability tracking
- Slot management
"""
import json
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Any, Union

from core.database import (
    get_cursor, transaction, execute_query, execute_one,
    execute_write, execute_insert, row_to_dict, rows_to_dicts
)
from core.logging import get_logger, log_event_action
from core.events import EventState, RecurrenceType, RecurrenceConfig

logger = get_logger(__name__)


class EventRepository:
    """Repository for event data operations."""

    # =========================================================================
    # Event CRUD
    # =========================================================================

    @staticmethod
    def get_event(guild_id: int, event_name: str) -> Optional[EventState]:
        """
        Get a single event by guild and name.

        Args:
            guild_id: Discord guild ID
            event_name: Name of the event

        Returns:
            EventState or None if not found
        """
        row = execute_one(
            """
            SELECT * FROM events
            WHERE guild_id = ? AND event_name = ?
            """,
            (str(guild_id), event_name)
        )

        if not row:
            return None

        return EventRepository._row_to_event_state(dict(row), guild_id)

    @staticmethod
    def get_event_by_id(event_id: str) -> Optional[EventState]:
        """
        Get a single event by ID.

        Args:
            event_id: UUID of the event

        Returns:
            EventState or None if not found
        """
        row = execute_one(
            "SELECT * FROM events WHERE event_id = ?",
            (event_id,)
        )

        if not row:
            return None

        return EventRepository._row_to_event_state(dict(row), int(row["guild_id"]))

    @staticmethod
    def get_events(guild_id: int, name_filter: Optional[str] = None) -> Dict[str, EventState]:
        """
        Get all events for a guild, optionally filtered by name.

        Args:
            guild_id: Discord guild ID
            name_filter: Optional name pattern to filter by

        Returns:
            Dict mapping event_name -> EventState
        """
        if name_filter:
            # First try exact match (case-insensitive)
            rows = execute_query(
                """
                SELECT * FROM events
                WHERE guild_id = ? AND LOWER(event_name) = LOWER(?)
                """,
                (str(guild_id), name_filter)
            )

            if rows:
                events = {}
                for row in rows:
                    event = EventRepository._row_to_event_state(dict(row), guild_id)
                    events[event.event_name] = event
                return events

            # Then try partial match
            rows = execute_query(
                """
                SELECT * FROM events
                WHERE guild_id = ? AND (
                    LOWER(event_name) LIKE LOWER(?) OR
                    LOWER(event_name) LIKE LOWER(?)
                )
                """,
                (str(guild_id), f"%{name_filter}%", f"{name_filter}%")
            )
        else:
            rows = execute_query(
                "SELECT * FROM events WHERE guild_id = ?",
                (str(guild_id),)
            )

        events = {}
        for row in rows:
            event = EventRepository._row_to_event_state(dict(row), guild_id)
            events[event.event_name] = event

        return events

    @staticmethod
    def get_all_events() -> Dict[str, Dict[str, EventState]]:
        """
        Get all events across all guilds.

        Returns:
            Dict mapping guild_id -> {event_name -> EventState}
        """
        rows = execute_query("SELECT * FROM events")

        result = {}
        for row in rows:
            guild_id = row["guild_id"]
            if guild_id not in result:
                result[guild_id] = {}

            event = EventRepository._row_to_event_state(dict(row), int(guild_id))
            result[guild_id][event.event_name] = event

        return result

    @staticmethod
    def count_events(guild_id: int) -> int:
        """Count the number of events for a guild."""
        row = execute_one(
            "SELECT COUNT(*) as count FROM events WHERE guild_id = ?",
            (str(guild_id),)
        )
        return row["count"] if row else 0

    @staticmethod
    def create_event(event: EventState) -> bool:
        """
        Create a new event.

        Args:
            event: EventState to create

        Returns:
            True if created successfully
        """
        try:
            with transaction() as cursor:
                # Insert event
                cursor.execute(
                    """
                    INSERT INTO events (
                        event_id, guild_id, event_name, max_attendees,
                        organizer, organizer_cname, confirmed_date,
                        bulletin_channel_id, bulletin_message_id, bulletin_thread_id,
                        recurrence_type, recurrence_interval, recurrence_end_date,
                        recurrence_occurrences, parent_event_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.event_id or str(uuid.uuid4()),
                        str(event.guild_id),
                        event.event_name,
                        int(event.max_attendees) if event.max_attendees else 0,
                        str(event.organizer),
                        event.organizer_cname,
                        event.confirmed_date,
                        str(event.bulletin_channel_id) if event.bulletin_channel_id else None,
                        str(event.bulletin_message_id) if event.bulletin_message_id else None,
                        str(event.bulletin_thread_id) if event.bulletin_thread_id else None,
                        event.recurrence.type.value if event.recurrence else "none",
                        event.recurrence.interval if event.recurrence else 1,
                        event.recurrence.end_date if event.recurrence else None,
                        event.recurrence.occurrences if event.recurrence else None,
                        event.recurrence.parent_event_id if event.recurrence else None,
                    )
                )

                event_id = event.event_id or cursor.lastrowid

                # Insert slots
                for slot in event.slots:
                    cursor.execute(
                        "INSERT OR IGNORE INTO event_slots (event_id, slot_time) VALUES (?, ?)",
                        (event_id, slot)
                    )

                # Insert RSVPs
                for user_id in event.rsvp:
                    cursor.execute(
                        "INSERT OR IGNORE INTO event_rsvps (event_id, user_id) VALUES (?, ?)",
                        (event_id, str(user_id))
                    )

                # Insert availability
                for slot_time, users in event.availability.items():
                    for position, user_id in users.items():
                        cursor.execute(
                            """
                            INSERT OR IGNORE INTO event_availability
                            (event_id, slot_time, user_id, position)
                            VALUES (?, ?, ?, ?)
                            """,
                            (event_id, slot_time, str(user_id), int(position))
                        )

                # Insert waitlist
                for slot_time, users in event.waitlist.items():
                    for position, user_id in users.items():
                        cursor.execute(
                            """
                            INSERT OR IGNORE INTO event_waitlist
                            (event_id, slot_time, user_id, position)
                            VALUES (?, ?, ?, ?)
                            """,
                            (event_id, slot_time, str(user_id), int(position))
                        )

                # Insert message map
                for slot_time, mapping in event.availability_to_message_map.items():
                    cursor.execute(
                        """
                        INSERT OR REPLACE INTO bulletin_message_map
                        (event_id, slot_time, thread_id, message_id, embed_index, field_name)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            event_id, slot_time,
                            str(mapping.get("thread_id")) if mapping.get("thread_id") else None,
                            str(mapping.get("message_id")) if mapping.get("message_id") else None,
                            mapping.get("embed_index"),
                            mapping.get("field_name")
                        )
                    )

            log_event_action("create", event.guild_id, event.event_name)
            logger.info(f"Created event '{event.event_name}' in guild {event.guild_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to create event: {e}")
            return False

    @staticmethod
    def update_event(event: EventState) -> bool:
        """
        Update an existing event.

        Args:
            event: EventState with updated data

        Returns:
            True if updated successfully
        """
        try:
            with transaction() as cursor:
                # Update main event record
                cursor.execute(
                    """
                    UPDATE events SET
                        event_name = ?,
                        max_attendees = ?,
                        organizer = ?,
                        organizer_cname = ?,
                        confirmed_date = ?,
                        bulletin_channel_id = ?,
                        bulletin_message_id = ?,
                        bulletin_thread_id = ?,
                        recurrence_type = ?,
                        recurrence_interval = ?,
                        recurrence_end_date = ?,
                        recurrence_occurrences = ?,
                        parent_event_id = ?,
                        updated_at = datetime('now')
                    WHERE event_id = ?
                    """,
                    (
                        event.event_name,
                        int(event.max_attendees) if event.max_attendees else 0,
                        str(event.organizer),
                        event.organizer_cname,
                        event.confirmed_date,
                        str(event.bulletin_channel_id) if event.bulletin_channel_id else None,
                        str(event.bulletin_message_id) if event.bulletin_message_id else None,
                        str(event.bulletin_thread_id) if event.bulletin_thread_id else None,
                        event.recurrence.type.value if event.recurrence else "none",
                        event.recurrence.interval if event.recurrence else 1,
                        event.recurrence.end_date if event.recurrence else None,
                        event.recurrence.occurrences if event.recurrence else None,
                        event.recurrence.parent_event_id if event.recurrence else None,
                        event.event_id
                    )
                )

                # Update slots - clear and re-insert
                cursor.execute("DELETE FROM event_slots WHERE event_id = ?", (event.event_id,))
                for slot in event.slots:
                    cursor.execute(
                        "INSERT INTO event_slots (event_id, slot_time) VALUES (?, ?)",
                        (event.event_id, slot)
                    )

                # Update RSVPs - clear and re-insert
                cursor.execute("DELETE FROM event_rsvps WHERE event_id = ?", (event.event_id,))
                for user_id in event.rsvp:
                    cursor.execute(
                        "INSERT INTO event_rsvps (event_id, user_id) VALUES (?, ?)",
                        (event.event_id, str(user_id))
                    )

                # Update availability - clear and re-insert
                cursor.execute("DELETE FROM event_availability WHERE event_id = ?", (event.event_id,))
                for slot_time, users in event.availability.items():
                    for position, user_id in users.items():
                        cursor.execute(
                            """
                            INSERT INTO event_availability
                            (event_id, slot_time, user_id, position)
                            VALUES (?, ?, ?, ?)
                            """,
                            (event.event_id, slot_time, str(user_id), int(position))
                        )

                # Update waitlist - clear and re-insert
                cursor.execute("DELETE FROM event_waitlist WHERE event_id = ?", (event.event_id,))
                for slot_time, users in event.waitlist.items():
                    for position, user_id in users.items():
                        cursor.execute(
                            """
                            INSERT INTO event_waitlist
                            (event_id, slot_time, user_id, position)
                            VALUES (?, ?, ?, ?)
                            """,
                            (event.event_id, slot_time, str(user_id), int(position))
                        )

                # Update message map
                cursor.execute("DELETE FROM bulletin_message_map WHERE event_id = ?", (event.event_id,))
                for slot_time, mapping in event.availability_to_message_map.items():
                    cursor.execute(
                        """
                        INSERT INTO bulletin_message_map
                        (event_id, slot_time, thread_id, message_id, embed_index, field_name)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            event.event_id, slot_time,
                            str(mapping.get("thread_id")) if mapping.get("thread_id") else None,
                            str(mapping.get("message_id")) if mapping.get("message_id") else None,
                            mapping.get("embed_index"),
                            mapping.get("field_name")
                        )
                    )

            log_event_action("update", event.guild_id, event.event_name)
            return True

        except Exception as e:
            logger.error(f"Failed to update event: {e}")
            return False

    @staticmethod
    def delete_event(guild_id: int, event_name: str) -> bool:
        """
        Delete an event.

        Args:
            guild_id: Discord guild ID
            event_name: Name of the event

        Returns:
            True if deleted successfully
        """
        try:
            # Get event_id first for cascade deletes
            event = EventRepository.get_event(guild_id, event_name)
            if not event:
                return False

            execute_write(
                "DELETE FROM events WHERE event_id = ?",
                (event.event_id,)
            )

            log_event_action("delete", guild_id, event_name)
            logger.info(f"Deleted event '{event_name}' from guild {guild_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to delete event: {e}")
            return False

    # =========================================================================
    # Helper Methods
    # =========================================================================

    @staticmethod
    def _row_to_event_state(row: dict, guild_id: int) -> EventState:
        """Convert a database row to an EventState object."""
        event_id = row["event_id"]

        # Get slots
        slot_rows = execute_query(
            "SELECT slot_time FROM event_slots WHERE event_id = ?",
            (event_id,)
        )
        slots = [r["slot_time"] for r in slot_rows]

        # Get RSVPs
        rsvp_rows = execute_query(
            "SELECT user_id FROM event_rsvps WHERE event_id = ?",
            (event_id,)
        )
        rsvp = [r["user_id"] for r in rsvp_rows]

        # Get availability
        avail_rows = execute_query(
            "SELECT slot_time, user_id, position FROM event_availability WHERE event_id = ?",
            (event_id,)
        )
        availability = {}
        for r in avail_rows:
            slot = r["slot_time"]
            if slot not in availability:
                availability[slot] = {}
            availability[slot][str(r["position"])] = r["user_id"]

        # Get waitlist
        waitlist_rows = execute_query(
            "SELECT slot_time, user_id, position FROM event_waitlist WHERE event_id = ?",
            (event_id,)
        )
        waitlist = {}
        for r in waitlist_rows:
            slot = r["slot_time"]
            if slot not in waitlist:
                waitlist[slot] = {}
            waitlist[slot][str(r["position"])] = r["user_id"]

        # Get message map
        map_rows = execute_query(
            "SELECT * FROM bulletin_message_map WHERE event_id = ?",
            (event_id,)
        )
        message_map = {}
        for r in map_rows:
            message_map[r["slot_time"]] = {
                "thread_id": int(r["thread_id"]) if r["thread_id"] else None,
                "message_id": int(r["message_id"]) if r["message_id"] else None,
                "embed_index": r["embed_index"],
                "field_name": r["field_name"]
            }

        # Build recurrence config
        recurrence = None
        if row.get("recurrence_type") and row["recurrence_type"] != "none":
            recurrence = RecurrenceConfig(
                type=RecurrenceType(row["recurrence_type"]),
                interval=row.get("recurrence_interval", 1),
                end_date=row.get("recurrence_end_date"),
                occurrences=row.get("recurrence_occurrences"),
                parent_event_id=row.get("parent_event_id")
            )

        return EventState(
            guild_id=str(guild_id),
            event_name=row["event_name"],
            event_id=event_id,
            max_attendees=str(row.get("max_attendees", 0)),
            organizer=row["organizer"],
            organizer_cname=row.get("organizer_cname", ""),
            confirmed_date=row.get("confirmed_date", "TBD"),
            bulletin_channel_id=int(row["bulletin_channel_id"]) if row.get("bulletin_channel_id") else None,
            bulletin_message_id=int(row["bulletin_message_id"]) if row.get("bulletin_message_id") else None,
            bulletin_thread_id=int(row["bulletin_thread_id"]) if row.get("bulletin_thread_id") else None,
            rsvp=rsvp,
            slots=slots,
            availability=availability,
            waitlist=waitlist,
            availability_to_message_map=message_map,
            recurrence=recurrence
        )

    # =========================================================================
    # Convenience Methods for Specific Operations
    # =========================================================================

    @staticmethod
    def add_rsvp(event_id: str, user_id: str) -> bool:
        """Add a user to an event's RSVP list."""
        try:
            execute_write(
                "INSERT OR IGNORE INTO event_rsvps (event_id, user_id) VALUES (?, ?)",
                (event_id, user_id)
            )
            return True
        except Exception as e:
            logger.error(f"Failed to add RSVP: {e}")
            return False

    @staticmethod
    def remove_rsvp(event_id: str, user_id: str) -> bool:
        """Remove a user from an event's RSVP list."""
        try:
            execute_write(
                "DELETE FROM event_rsvps WHERE event_id = ? AND user_id = ?",
                (event_id, user_id)
            )
            return True
        except Exception as e:
            logger.error(f"Failed to remove RSVP: {e}")
            return False

    @staticmethod
    def set_availability(event_id: str, slot_time: str, user_id: str, position: int) -> bool:
        """Set a user's availability for a specific slot."""
        try:
            execute_write(
                """
                INSERT OR REPLACE INTO event_availability
                (event_id, slot_time, user_id, position)
                VALUES (?, ?, ?, ?)
                """,
                (event_id, slot_time, user_id, position)
            )
            return True
        except Exception as e:
            logger.error(f"Failed to set availability: {e}")
            return False

    @staticmethod
    def remove_availability(event_id: str, slot_time: str, user_id: str) -> bool:
        """Remove a user's availability for a specific slot."""
        try:
            execute_write(
                """
                DELETE FROM event_availability
                WHERE event_id = ? AND slot_time = ? AND user_id = ?
                """,
                (event_id, slot_time, user_id)
            )
            return True
        except Exception as e:
            logger.error(f"Failed to remove availability: {e}")
            return False

    @staticmethod
    def update_bulletin_info(
        event_id: str,
        channel_id: Optional[int],
        message_id: Optional[int],
        thread_id: Optional[int]
    ) -> bool:
        """Update an event's bulletin channel/message IDs."""
        try:
            execute_write(
                """
                UPDATE events SET
                    bulletin_channel_id = ?,
                    bulletin_message_id = ?,
                    bulletin_thread_id = ?,
                    updated_at = datetime('now')
                WHERE event_id = ?
                """,
                (
                    str(channel_id) if channel_id else None,
                    str(message_id) if message_id else None,
                    str(thread_id) if thread_id else None,
                    event_id
                )
            )
            return True
        except Exception as e:
            logger.error(f"Failed to update bulletin info: {e}")
            return False
