#!/usr/bin/env python3
"""
Migration Script: JSON to SQLite

Migrates all existing JSON data files to the new SQLite database.
This is a one-time migration script for Phase 4.

Usage:
    python scripts/migrate_json_to_sqlite.py [--dry-run] [--verbose]

Options:
    --dry-run    Preview changes without writing to database
    --verbose    Show detailed migration progress
"""
import argparse
import json
import sys
from pathlib import Path
from datetime import datetime

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import config
from core.database import init_database, get_cursor, transaction
from core.storage import read_json
from core.logging import get_logger

logger = get_logger(__name__)


# =============================================================================
# Data File Paths
# =============================================================================

DATA_DIR = Path(config.DATA_DIR)

JSON_FILES = {
    "events": DATA_DIR / "events.json",
    "guild_config": DATA_DIR / "guild_config.json",
    "user_timezones": DATA_DIR / "user_timezones.json",
    "notifications": DATA_DIR / "notifications.json",
    "availability_memory": DATA_DIR / "availability_memory.json",
}


# =============================================================================
# Migration Functions
# =============================================================================

def migrate_events(dry_run: bool = False, verbose: bool = False) -> int:
    """
    Migrate events.json to SQLite.

    Returns:
        Number of events migrated
    """
    events_file = JSON_FILES["events"]
    if not events_file.exists():
        if verbose:
            print(f"  No events file found at {events_file}")
        return 0

    try:
        raw = read_json(str(events_file.name))
    except Exception as e:
        print(f"  Error reading events.json: {e}")
        return 0

    count = 0

    for guild_id, guild_data in raw.items():
        events = guild_data.get("events", {})

        for event_name, event_data in events.items():
            if verbose:
                print(f"  Migrating event: {event_name} (guild {guild_id})")

            if dry_run:
                count += 1
                continue

            try:
                with transaction() as cursor:
                    # Insert event
                    event_id = event_data.get("event_id", f"migrated-{guild_id}-{event_name}")

                    # Handle recurrence
                    recurrence = event_data.get("recurrence", {})
                    recurrence_type = recurrence.get("type", "none") if recurrence else "none"

                    cursor.execute(
                        """
                        INSERT OR REPLACE INTO events (
                            event_id, guild_id, event_name, max_attendees,
                            organizer, organizer_cname, confirmed_date,
                            bulletin_channel_id, bulletin_message_id, bulletin_thread_id,
                            recurrence_type, recurrence_interval, recurrence_end_date,
                            recurrence_occurrences, parent_event_id
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            event_id,
                            str(guild_id),
                            event_name,
                            int(event_data.get("max_attendees", 0)) if event_data.get("max_attendees") else 0,
                            str(event_data.get("organizer", "")),
                            event_data.get("organizer_cname", ""),
                            event_data.get("confirmed_date", "TBD"),
                            str(event_data.get("bulletin_channel_id")) if event_data.get("bulletin_channel_id") else None,
                            str(event_data.get("bulletin_message_id")) if event_data.get("bulletin_message_id") else None,
                            str(event_data.get("bulletin_thread_id")) if event_data.get("bulletin_thread_id") else None,
                            recurrence_type,
                            recurrence.get("interval", 1) if recurrence else 1,
                            recurrence.get("end_date") if recurrence else None,
                            recurrence.get("occurrences") if recurrence else None,
                            recurrence.get("parent_event_id") if recurrence else None,
                        )
                    )

                    # Insert slots
                    for slot in event_data.get("slots", []):
                        cursor.execute(
                            "INSERT OR IGNORE INTO event_slots (event_id, slot_time) VALUES (?, ?)",
                            (event_id, slot)
                        )

                    # Insert RSVPs
                    for user_id in event_data.get("rsvp", []):
                        cursor.execute(
                            "INSERT OR IGNORE INTO event_rsvps (event_id, user_id) VALUES (?, ?)",
                            (event_id, str(user_id))
                        )

                    # Insert availability
                    for slot_time, users in event_data.get("availability", {}).items():
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
                    for slot_time, users in event_data.get("waitlist", {}).items():
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
                    for slot_time, mapping in event_data.get("availability_to_message_map", {}).items():
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

                count += 1

            except Exception as e:
                print(f"  Error migrating event {event_name}: {e}")

    return count


def migrate_configs(dry_run: bool = False, verbose: bool = False) -> int:
    """
    Migrate guild_config.json to SQLite.

    Returns:
        Number of configs migrated
    """
    config_file = JSON_FILES["guild_config"]
    if not config_file.exists():
        if verbose:
            print(f"  No config file found at {config_file}")
        return 0

    try:
        raw = read_json(str(config_file.name))
    except Exception as e:
        print(f"  Error reading guild_config.json: {e}")
        return 0

    count = 0
    servers = raw.get("servers", {})

    for guild_id, guild_data in servers.items():
        config_data = guild_data.get("config", {})

        if verbose:
            print(f"  Migrating config for guild {guild_id}")

        if dry_run:
            count += 1
            continue

        try:
            with transaction() as cursor:
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO guild_configs (
                        guild_id, admin_roles, event_organizer_roles, event_attendee_roles,
                        bulletin_channel, roles_and_permissions_settings_enabled,
                        bulletin_settings_enabled, display_settings_enabled,
                        notifications_enabled, default_reminder_minutes, notification_channel
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(guild_id),
                        json.dumps(config_data.get("admin_roles", [])),
                        json.dumps(config_data.get("event_organizer_roles", [])),
                        json.dumps(config_data.get("event_attendee_roles", [])),
                        config_data.get("bulletin_channel"),
                        1 if config_data.get("roles_and_permissions_settings_enabled", True) else 0,
                        1 if config_data.get("bulletin_settings_enabled", False) else 0,
                        1 if config_data.get("display_settings_enabled", True) else 0,
                        1 if config_data.get("notifications_enabled", True) else 0,
                        config_data.get("default_reminder_minutes", 60),
                        config_data.get("notification_channel")
                    )
                )
            count += 1

        except Exception as e:
            print(f"  Error migrating config for guild {guild_id}: {e}")

    return count


def migrate_user_timezones(dry_run: bool = False, verbose: bool = False) -> int:
    """
    Migrate user_timezones.json to SQLite.

    Returns:
        Number of users migrated
    """
    tz_file = JSON_FILES["user_timezones"]
    if not tz_file.exists():
        if verbose:
            print(f"  No timezone file found at {tz_file}")
        return 0

    try:
        raw = read_json(str(tz_file.name))
    except Exception as e:
        print(f"  Error reading user_timezones.json: {e}")
        return 0

    count = 0

    for user_id, user_data in raw.items():
        timezone = user_data.get("timezone") if isinstance(user_data, dict) else user_data

        if verbose:
            print(f"  Migrating timezone for user {user_id}: {timezone}")

        if dry_run:
            count += 1
            continue

        if timezone:
            try:
                with transaction() as cursor:
                    cursor.execute(
                        """
                        INSERT OR REPLACE INTO user_data (user_id, timezone)
                        VALUES (?, ?)
                        """,
                        (str(user_id), timezone)
                    )
                count += 1

            except Exception as e:
                print(f"  Error migrating timezone for user {user_id}: {e}")

    return count


def migrate_notifications(dry_run: bool = False, verbose: bool = False) -> int:
    """
    Migrate notifications.json to SQLite.

    Returns:
        Number of preferences migrated
    """
    notif_file = JSON_FILES["notifications"]
    if not notif_file.exists():
        if verbose:
            print(f"  No notifications file found at {notif_file}")
        return 0

    try:
        raw = read_json(str(notif_file.name))
    except Exception as e:
        print(f"  Error reading notifications.json: {e}")
        return 0

    count = 0
    preferences = raw.get("preferences", {})

    for key, events in preferences.items():
        # Key format: "guild_id:user_id"
        parts = key.split(":")
        if len(parts) != 2:
            continue

        guild_id, user_id = parts

        for event_name, pref_data in events.items():
            if verbose:
                print(f"  Migrating notification pref: user {user_id}, event {event_name}")

            if dry_run:
                count += 1
                continue

            try:
                with transaction() as cursor:
                    cursor.execute(
                        """
                        INSERT OR REPLACE INTO notification_preferences (
                            user_id, guild_id, event_name, reminder_minutes,
                            notify_on_start, notify_on_change, notify_on_cancel
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            str(user_id),
                            str(guild_id),
                            event_name,
                            pref_data.get("reminder_minutes", 60),
                            1 if pref_data.get("notify_on_start", True) else 0,
                            1 if pref_data.get("notify_on_change", True) else 0,
                            1 if pref_data.get("notify_on_cancel", True) else 0
                        )
                    )
                count += 1

            except Exception as e:
                print(f"  Error migrating notification pref: {e}")

    return count


def migrate_availability_memory(dry_run: bool = False, verbose: bool = False) -> int:
    """
    Migrate availability_memory.json to SQLite.

    Returns:
        Number of patterns migrated
    """
    avail_file = JSON_FILES["availability_memory"]
    if not avail_file.exists():
        if verbose:
            print(f"  No availability memory file found at {avail_file}")
        return 0

    try:
        raw = read_json(str(avail_file.name))
    except Exception as e:
        print(f"  Error reading availability_memory.json: {e}")
        return 0

    count = 0

    for guild_id, users in raw.items():
        for user_id, user_data in users.items():
            patterns = user_data.get("patterns", [])

            for pattern in patterns:
                if verbose:
                    print(f"  Migrating pattern: user {user_id}, day {pattern.get('day_of_week')}, hour {pattern.get('hour')}")

                if dry_run:
                    count += 1
                    continue

                try:
                    with transaction() as cursor:
                        cursor.execute(
                            """
                            INSERT OR REPLACE INTO availability_patterns (
                                user_id, guild_id, day_of_week, hour, count, last_used
                            ) VALUES (?, ?, ?, ?, ?, ?)
                            """,
                            (
                                str(user_id),
                                str(guild_id),
                                pattern.get("day_of_week", 0),
                                pattern.get("hour", 0),
                                pattern.get("count", 1),
                                pattern.get("last_used", datetime.utcnow().isoformat())
                            )
                        )
                    count += 1

                except Exception as e:
                    print(f"  Error migrating availability pattern: {e}")

    return count


# =============================================================================
# Main Migration
# =============================================================================

def run_migration(dry_run: bool = False, verbose: bool = False) -> dict:
    """
    Run the full migration from JSON to SQLite.

    Args:
        dry_run: If True, only preview changes
        verbose: If True, show detailed progress

    Returns:
        Dict with migration statistics
    """
    print("=" * 60)
    print("Event Bot: JSON to SQLite Migration")
    print("=" * 60)

    if dry_run:
        print("\n*** DRY RUN MODE - No changes will be made ***\n")

    # Initialize database (creates tables if needed)
    if not dry_run:
        print("Initializing database...")
        init_database()
        print("Database initialized.\n")

    stats = {}

    # Migrate events
    print("Migrating events...")
    stats["events"] = migrate_events(dry_run, verbose)
    print(f"  Migrated {stats['events']} events\n")

    # Migrate configs
    print("Migrating guild configs...")
    stats["configs"] = migrate_configs(dry_run, verbose)
    print(f"  Migrated {stats['configs']} configs\n")

    # Migrate user timezones
    print("Migrating user timezones...")
    stats["timezones"] = migrate_user_timezones(dry_run, verbose)
    print(f"  Migrated {stats['timezones']} user timezones\n")

    # Migrate notifications
    print("Migrating notification preferences...")
    stats["notifications"] = migrate_notifications(dry_run, verbose)
    print(f"  Migrated {stats['notifications']} notification preferences\n")

    # Migrate availability memory
    print("Migrating availability patterns...")
    stats["availability"] = migrate_availability_memory(dry_run, verbose)
    print(f"  Migrated {stats['availability']} availability patterns\n")

    # Summary
    print("=" * 60)
    print("Migration Summary")
    print("=" * 60)
    total = sum(stats.values())
    print(f"  Events:          {stats['events']}")
    print(f"  Configs:         {stats['configs']}")
    print(f"  User Timezones:  {stats['timezones']}")
    print(f"  Notifications:   {stats['notifications']}")
    print(f"  Availability:    {stats['availability']}")
    print(f"  ---")
    print(f"  Total Records:   {total}")
    print()

    if dry_run:
        print("*** DRY RUN COMPLETE - No changes were made ***")
    else:
        print("Migration complete!")
        print("\nNote: JSON files have been preserved. You can delete them")
        print("after verifying the migration was successful.")

    return stats


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Migrate Event Bot data from JSON to SQLite"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without writing to database"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show detailed migration progress"
    )

    args = parser.parse_args()
    run_migration(dry_run=args.dry_run, verbose=args.verbose)
