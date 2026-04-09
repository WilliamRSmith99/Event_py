"""
Tests for /export iCal generation (commands/event/export.py).

build_ical() is a pure function — no Discord or DB mocking needed.
"""
import pytest
from core.events import EventState
from commands.event.export import build_ical, _escape


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_event(
    name="Game Night",
    confirmed_date="TBD",
    slots=None,
    availability=None,
):
    return EventState(
        guild_id="123",
        event_name=name,
        max_attendees="10",
        organizer=1,
        organizer_cname="TestOrg",
        confirmed_date=confirmed_date,
        slots=slots or [],
        availability=availability or {},
        rsvp=[],
    )


# ---------------------------------------------------------------------------
# Structure / format
# ---------------------------------------------------------------------------

def test_ical_wrapper_is_valid():
    """VCALENDAR wrapper is present and well-formed."""
    event = make_event(confirmed_date="2026-06-15T18:00:00")
    ical = build_ical(event)
    assert ical.startswith("BEGIN:VCALENDAR")
    assert ical.strip().endswith("END:VCALENDAR")
    assert "VERSION:2.0" in ical
    assert "PRODID:" in ical


def test_confirmed_event_produces_exactly_one_vevent():
    event = make_event(confirmed_date="2026-06-15T18:00:00")
    ical = build_ical(event)
    assert ical.count("BEGIN:VEVENT") == 1
    assert ical.count("END:VEVENT") == 1


def test_confirmed_event_dtstart_is_correct():
    event = make_event(confirmed_date="2026-06-15T18:00:00")
    ical = build_ical(event)
    assert "DTSTART:20260615T180000Z" in ical


def test_confirmed_event_dtend_is_one_hour_later():
    event = make_event(confirmed_date="2026-06-15T18:00:00")
    ical = build_ical(event)
    assert "DTEND:20260615T190000Z" in ical


def test_confirmed_event_summary_contains_name():
    event = make_event(name="Raid Night", confirmed_date="2026-06-15T18:00:00")
    ical = build_ical(event)
    assert "Raid Night" in ical


# ---------------------------------------------------------------------------
# TBD / proposed slots
# ---------------------------------------------------------------------------

def test_tbd_event_produces_one_vevent_per_slot():
    event = make_event(slots=[
        "2026-06-15T18:00:00",
        "2026-06-16T19:00:00",
        "2026-06-17T20:00:00",
    ])
    ical = build_ical(event)
    assert ical.count("BEGIN:VEVENT") == 3


def test_tbd_event_labels_slots_as_proposed():
    event = make_event(slots=["2026-06-15T18:00:00"])
    ical = build_ical(event)
    assert "(proposed)" in ical


def test_rsvp_count_in_slot_description():
    slot = "2026-06-15T18:00:00"
    event = make_event(
        slots=[slot],
        availability={slot: {"1": 100, "2": 200}},
    )
    ical = build_ical(event)
    assert "2 available" in ical


def test_zero_rsvp_slots_still_appear():
    event = make_event(slots=["2026-06-15T18:00:00"])
    ical = build_ical(event)
    assert "BEGIN:VEVENT" in ical
    assert "0 available" in ical


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_no_slots_and_tbd_returns_empty_string():
    event = make_event()  # no slots, confirmed_date="TBD"
    assert build_ical(event) == ""


def test_special_chars_escaped_in_summary():
    """Commas, semicolons, and backslashes must be escaped per RFC 5545."""
    event = make_event(name=r"Event, with; special\chars", confirmed_date="2026-06-15T18:00:00")
    ical = build_ical(event)
    assert r"Event\, with\; special\\chars" in ical


def test_escape_helper():
    assert _escape("a,b;c\\d\ne") == r"a\,b\;c\\d\ne"


def test_uid_is_unique_per_event():
    e1 = make_event(confirmed_date="2026-06-15T18:00:00")
    e2 = make_event(confirmed_date="2026-06-15T18:00:00")
    # Different event IDs → different UIDs
    ical1 = build_ical(e1)
    ical2 = build_ical(e2)
    uid1 = next(line for line in ical1.splitlines() if line.startswith("UID:"))
    uid2 = next(line for line in ical2.splitlines() if line.startswith("UID:"))
    assert uid1 != uid2
