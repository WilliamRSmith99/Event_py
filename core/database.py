"""
SQLite Database Module for Event Bot.

Provides connection management, schema initialization, and database utilities.
This module serves as the foundation for persistent data storage.
"""
import sqlite3
import os
from contextlib import contextmanager
from typing import Optional, Generator, Any
from pathlib import Path

from core.logging import get_logger
import config

logger = get_logger(__name__)

# Database file path
DB_PATH = Path(config.DATA_DIR) / "eventbot.db"

# Schema version for migrations
SCHEMA_VERSION = 1


# =============================================================================
# Schema Definition
# =============================================================================

SCHEMA_SQL = """
-- Schema version tracking
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT DEFAULT (datetime('now'))
);

-- =============================================================================
-- Guild Configuration
-- =============================================================================
CREATE TABLE IF NOT EXISTS guild_configs (
    guild_id TEXT PRIMARY KEY,
    admin_roles TEXT DEFAULT '[]',  -- JSON array of role IDs
    event_organizer_roles TEXT DEFAULT '[]',  -- JSON array of role IDs
    event_attendee_roles TEXT DEFAULT '[]',  -- JSON array of role IDs
    bulletin_channel TEXT,
    roles_and_permissions_settings_enabled INTEGER DEFAULT 1,
    bulletin_settings_enabled INTEGER DEFAULT 0,
    display_settings_enabled INTEGER DEFAULT 1,
    notifications_enabled INTEGER DEFAULT 1,
    default_reminder_minutes INTEGER DEFAULT 60,
    notification_channel TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

-- =============================================================================
-- Subscriptions (Premium)
-- =============================================================================
CREATE TABLE IF NOT EXISTS subscriptions (
    guild_id TEXT PRIMARY KEY,
    tier TEXT DEFAULT 'free' CHECK (tier IN ('free', 'premium')),
    expires_at TEXT,  -- ISO datetime or NULL for free tier
    stripe_customer_id TEXT,
    stripe_subscription_id TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_subscriptions_stripe_customer
    ON subscriptions(stripe_customer_id);
CREATE INDEX IF NOT EXISTS idx_subscriptions_expires
    ON subscriptions(expires_at);

-- =============================================================================
-- Events
-- =============================================================================
CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY,
    guild_id TEXT NOT NULL,
    event_name TEXT NOT NULL,
    max_attendees INTEGER DEFAULT 0,
    organizer TEXT NOT NULL,  -- User ID
    organizer_cname TEXT,  -- Display name
    confirmed_date TEXT,  -- ISO datetime or 'TBD'
    bulletin_channel_id TEXT,
    bulletin_message_id TEXT,
    bulletin_thread_id TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),

    -- Recurrence fields (Premium)
    recurrence_type TEXT DEFAULT 'none' CHECK (recurrence_type IN ('none', 'daily', 'weekly', 'biweekly', 'monthly')),
    recurrence_interval INTEGER DEFAULT 1,
    recurrence_end_date TEXT,
    recurrence_occurrences INTEGER,
    parent_event_id TEXT REFERENCES events(event_id),

    UNIQUE(guild_id, event_name)
);

CREATE INDEX IF NOT EXISTS idx_events_guild ON events(guild_id);
CREATE INDEX IF NOT EXISTS idx_events_organizer ON events(organizer);
CREATE INDEX IF NOT EXISTS idx_events_confirmed_date ON events(confirmed_date);
CREATE INDEX IF NOT EXISTS idx_events_parent ON events(parent_event_id);

-- =============================================================================
-- Event Slots (Proposed time slots)
-- =============================================================================
CREATE TABLE IF NOT EXISTS event_slots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL REFERENCES events(event_id) ON DELETE CASCADE,
    slot_time TEXT NOT NULL,  -- ISO datetime
    created_at TEXT DEFAULT (datetime('now')),

    UNIQUE(event_id, slot_time)
);

CREATE INDEX IF NOT EXISTS idx_event_slots_event ON event_slots(event_id);

-- =============================================================================
-- Event RSVPs
-- =============================================================================
CREATE TABLE IF NOT EXISTS event_rsvps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL REFERENCES events(event_id) ON DELETE CASCADE,
    user_id TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now')),

    UNIQUE(event_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_event_rsvps_event ON event_rsvps(event_id);
CREATE INDEX IF NOT EXISTS idx_event_rsvps_user ON event_rsvps(user_id);

-- =============================================================================
-- Event Availability (User availability per slot)
-- =============================================================================
CREATE TABLE IF NOT EXISTS event_availability (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL REFERENCES events(event_id) ON DELETE CASCADE,
    slot_time TEXT NOT NULL,  -- ISO datetime
    user_id TEXT NOT NULL,
    position INTEGER NOT NULL,  -- Queue position
    created_at TEXT DEFAULT (datetime('now')),

    UNIQUE(event_id, slot_time, user_id)
);

CREATE INDEX IF NOT EXISTS idx_event_availability_event ON event_availability(event_id);
CREATE INDEX IF NOT EXISTS idx_event_availability_slot ON event_availability(event_id, slot_time);
CREATE INDEX IF NOT EXISTS idx_event_availability_user ON event_availability(user_id);

-- =============================================================================
-- Event Waitlist
-- =============================================================================
CREATE TABLE IF NOT EXISTS event_waitlist (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL REFERENCES events(event_id) ON DELETE CASCADE,
    slot_time TEXT NOT NULL,  -- ISO datetime
    user_id TEXT NOT NULL,
    position INTEGER NOT NULL,  -- Queue position
    created_at TEXT DEFAULT (datetime('now')),

    UNIQUE(event_id, slot_time, user_id)
);

CREATE INDEX IF NOT EXISTS idx_event_waitlist_event ON event_waitlist(event_id);

-- =============================================================================
-- Bulletin Message Mapping (for updating embeds)
-- =============================================================================
CREATE TABLE IF NOT EXISTS bulletin_message_map (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL REFERENCES events(event_id) ON DELETE CASCADE,
    slot_time TEXT NOT NULL,  -- ISO datetime
    thread_id TEXT,
    message_id TEXT,
    embed_index INTEGER,
    field_name TEXT,
    created_at TEXT DEFAULT (datetime('now')),

    UNIQUE(event_id, slot_time)
);

CREATE INDEX IF NOT EXISTS idx_bulletin_message_map_event ON bulletin_message_map(event_id);

-- =============================================================================
-- User Data (Timezones)
-- =============================================================================
CREATE TABLE IF NOT EXISTS user_data (
    user_id TEXT PRIMARY KEY,
    timezone TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

-- =============================================================================
-- Notification Preferences
-- =============================================================================
CREATE TABLE IF NOT EXISTS notification_preferences (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    guild_id TEXT NOT NULL,
    event_name TEXT NOT NULL,
    reminder_minutes INTEGER DEFAULT 60,
    notify_on_start INTEGER DEFAULT 1,
    notify_on_change INTEGER DEFAULT 1,
    notify_on_cancel INTEGER DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),

    UNIQUE(user_id, guild_id, event_name)
);

CREATE INDEX IF NOT EXISTS idx_notification_prefs_user ON notification_preferences(user_id);
CREATE INDEX IF NOT EXISTS idx_notification_prefs_guild_event ON notification_preferences(guild_id, event_name);

-- =============================================================================
-- Scheduled Notifications
-- =============================================================================
CREATE TABLE IF NOT EXISTS scheduled_notifications (
    id TEXT PRIMARY KEY,
    notification_type TEXT NOT NULL CHECK (notification_type IN ('event_reminder', 'event_start', 'event_canceled', 'event_changed', 'event_confirmed')),
    user_id TEXT NOT NULL,
    guild_id TEXT NOT NULL,
    event_name TEXT NOT NULL,
    scheduled_time TEXT NOT NULL,  -- ISO datetime
    message TEXT NOT NULL,
    sent INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_scheduled_notifications_time ON scheduled_notifications(scheduled_time);
CREATE INDEX IF NOT EXISTS idx_scheduled_notifications_sent ON scheduled_notifications(sent);

-- =============================================================================
-- Availability Memory (Premium Feature)
-- =============================================================================
CREATE TABLE IF NOT EXISTS availability_patterns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    guild_id TEXT NOT NULL,
    day_of_week INTEGER NOT NULL CHECK (day_of_week BETWEEN 0 AND 6),
    hour INTEGER NOT NULL CHECK (hour BETWEEN 0 AND 23),
    count INTEGER DEFAULT 1,
    last_used TEXT DEFAULT (datetime('now')),
    created_at TEXT DEFAULT (datetime('now')),

    UNIQUE(user_id, guild_id, day_of_week, hour)
);

CREATE INDEX IF NOT EXISTS idx_availability_patterns_user_guild ON availability_patterns(user_id, guild_id);
"""


# =============================================================================
# Connection Management
# =============================================================================

_connection_pool: Optional[sqlite3.Connection] = None


def get_connection() -> sqlite3.Connection:
    """
    Get a database connection from the pool.

    Uses a simple single-connection approach suitable for the bot's
    single-threaded async nature.
    """
    global _connection_pool

    if _connection_pool is None:
        # Ensure data directory exists
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)

        _connection_pool = sqlite3.connect(
            str(DB_PATH),
            check_same_thread=False,
            isolation_level=None  # Autocommit mode
        )
        _connection_pool.row_factory = sqlite3.Row

        # Enable foreign keys
        _connection_pool.execute("PRAGMA foreign_keys = ON")

        # Performance optimizations
        _connection_pool.execute("PRAGMA journal_mode = WAL")
        _connection_pool.execute("PRAGMA synchronous = NORMAL")
        _connection_pool.execute("PRAGMA cache_size = -64000")  # 64MB cache

        logger.info(f"Database connection established: {DB_PATH}")

    return _connection_pool


@contextmanager
def get_cursor() -> Generator[sqlite3.Cursor, None, None]:
    """
    Context manager for getting a database cursor.

    Usage:
        with get_cursor() as cursor:
            cursor.execute("SELECT * FROM events")
            results = cursor.fetchall()
    """
    conn = get_connection()
    cursor = conn.cursor()
    try:
        yield cursor
    finally:
        cursor.close()


@contextmanager
def transaction() -> Generator[sqlite3.Cursor, None, None]:
    """
    Context manager for database transactions.

    Automatically commits on success, rolls back on exception.

    Usage:
        with transaction() as cursor:
            cursor.execute("INSERT INTO ...")
            cursor.execute("UPDATE ...")
    """
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("BEGIN")
        yield cursor
        cursor.execute("COMMIT")
    except Exception:
        cursor.execute("ROLLBACK")
        raise
    finally:
        cursor.close()


def close_connection() -> None:
    """Close the database connection."""
    global _connection_pool

    if _connection_pool is not None:
        _connection_pool.close()
        _connection_pool = None
        logger.info("Database connection closed")


# =============================================================================
# Schema Management
# =============================================================================

def init_database() -> None:
    """
    Initialize the database schema.

    Creates all tables if they don't exist and applies any pending migrations.
    """
    conn = get_connection()
    cursor = conn.cursor()

    try:
        # Create schema
        cursor.executescript(SCHEMA_SQL)

        # Check/set schema version
        cursor.execute("SELECT MAX(version) FROM schema_version")
        result = cursor.fetchone()
        current_version = result[0] if result[0] else 0

        if current_version < SCHEMA_VERSION:
            cursor.execute(
                "INSERT INTO schema_version (version) VALUES (?)",
                (SCHEMA_VERSION,)
            )
            logger.info(f"Database schema initialized to version {SCHEMA_VERSION}")
        else:
            logger.info(f"Database schema already at version {current_version}")

    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        raise
    finally:
        cursor.close()


def get_schema_version() -> int:
    """Get the current schema version."""
    with get_cursor() as cursor:
        cursor.execute("SELECT MAX(version) FROM schema_version")
        result = cursor.fetchone()
        return result[0] if result[0] else 0


# =============================================================================
# Utility Functions
# =============================================================================

def execute_query(query: str, params: tuple = ()) -> list:
    """
    Execute a SELECT query and return all results.

    Args:
        query: SQL query string
        params: Query parameters

    Returns:
        List of sqlite3.Row objects
    """
    with get_cursor() as cursor:
        cursor.execute(query, params)
        return cursor.fetchall()


def execute_one(query: str, params: tuple = ()) -> Optional[sqlite3.Row]:
    """
    Execute a SELECT query and return the first result.

    Args:
        query: SQL query string
        params: Query parameters

    Returns:
        sqlite3.Row object or None
    """
    with get_cursor() as cursor:
        cursor.execute(query, params)
        return cursor.fetchone()


def execute_write(query: str, params: tuple = ()) -> int:
    """
    Execute an INSERT/UPDATE/DELETE query.

    Args:
        query: SQL query string
        params: Query parameters

    Returns:
        Number of affected rows
    """
    with get_cursor() as cursor:
        cursor.execute(query, params)
        return cursor.rowcount


def execute_insert(query: str, params: tuple = ()) -> int:
    """
    Execute an INSERT query and return the last row ID.

    Args:
        query: SQL query string
        params: Query parameters

    Returns:
        Last inserted row ID
    """
    with get_cursor() as cursor:
        cursor.execute(query, params)
        return cursor.lastrowid


def row_to_dict(row: Optional[sqlite3.Row]) -> Optional[dict]:
    """Convert a sqlite3.Row to a dictionary."""
    if row is None:
        return None
    return dict(row)


def rows_to_dicts(rows: list) -> list:
    """Convert a list of sqlite3.Row objects to dictionaries."""
    return [dict(row) for row in rows]
