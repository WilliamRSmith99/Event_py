"""
Tests for core/events.py CRUD operations against a real (test-isolated) SQLite DB.

The fresh_db fixture in conftest.py handles DB setup/teardown automatically.
"""
import pytest
from datetime import datetime, timedelta

from core.events import (
    EventState,
    modify_event,
    get_event,
    get_events,
    delete_event,
    rename_event,
    archive_event,
    get_active_events,
)


GUILD_ID = 12345


def make_event(name="Test Event", confirmed_date="TBD", **kwargs):
    return EventState(
        guild_id=str(GUILD_ID),
        event_name=name,
        max_attendees="10",
        organizer=1,
        organizer_cname="TestOrg",
        confirmed_date=confirmed_date,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Create / Read
# ---------------------------------------------------------------------------

def test_create_and_get_event():
    event = make_event("Alpha")
    modify_event(event)
    fetched = get_event(GUILD_ID, "Alpha")
    assert fetched is not None
    assert fetched.event_name == "Alpha"
    assert fetched.guild_id == str(GUILD_ID)


def test_modify_event_upsert_then_update():
    """Second modify_event call on same event_id should update, not duplicate."""
    event = make_event("Beta")
    modify_event(event)

    event.max_attendees = "20"
    modify_event(event)

    all_events = get_events(GUILD_ID)
    beta_events = [e for e in all_events.values() if e.event_name == "Beta"]
    assert len(beta_events) == 1
    assert beta_events[0].max_attendees == "20"


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

def test_delete_event():
    event = make_event("Gamma")
    modify_event(event)
    assert get_event(GUILD_ID, "Gamma") is not None

    result = delete_event(str(GUILD_ID), "Gamma")
    assert result is True
    assert get_event(GUILD_ID, "Gamma") is None


def test_delete_nonexistent_event_returns_false():
    result = delete_event(str(GUILD_ID), "DoesNotExist")
    assert result is False


# ---------------------------------------------------------------------------
# Rename
# ---------------------------------------------------------------------------

def test_rename_event():
    event = make_event("Delta")
    modify_event(event)

    renamed = rename_event(GUILD_ID, "Delta", "Epsilon")
    assert renamed is not None
    assert renamed.event_name == "Epsilon"
    assert get_event(GUILD_ID, "Epsilon") is not None
    assert get_event(GUILD_ID, "Delta") is None


def test_rename_to_existing_name_returns_none():
    modify_event(make_event("Zeta"))
    modify_event(make_event("Eta"))
    result = rename_event(GUILD_ID, "Zeta", "Eta")
    assert result is None  # name collision


# ---------------------------------------------------------------------------
# Archive
# ---------------------------------------------------------------------------

def test_archive_event():
    event = make_event("Theta")
    modify_event(event)

    result = archive_event(str(GUILD_ID), "Theta")
    assert result is True

    fetched = get_event(GUILD_ID, "Theta")
    assert fetched is not None
    assert fetched.is_archived is True
    assert fetched.archived_at is not None


def test_get_active_events_excludes_archived():
    event = make_event("Iota")
    modify_event(event)
    archive_event(str(GUILD_ID), "Iota")

    active = get_active_events(GUILD_ID)
    assert "Iota" not in active


def test_get_active_events_excludes_past():
    """Events whose confirmed_date is in the past should not appear in active."""
    past_date = (datetime.utcnow() - timedelta(days=1)).isoformat()
    event = make_event("Kappa", confirmed_date=past_date)
    modify_event(event)

    active = get_active_events(GUILD_ID)
    assert "Kappa" not in active
