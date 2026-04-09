"""
iCal export command.

Generates a .ics file for a single event (confirmed date or all proposed slots).
Free tier: works for any event.
"""
import io
import uuid
from datetime import datetime, timedelta, timezone

import discord

from core import events, userdata, utils
from core.logging import get_logger

logger = get_logger(__name__)

# iCal timestamp format (UTC)
_ICAL_DT = "%Y%m%dT%H%M%SZ"


def _utcnow_stamp() -> str:
    return datetime.now(timezone.utc).strftime(_ICAL_DT)


def _to_ical_dt(dt: datetime) -> str:
    """Convert a datetime (naive=UTC or aware) to iCal UTC format."""
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.strftime(_ICAL_DT)


def _escape(text: str) -> str:
    """Escape special characters for iCal text fields."""
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _vevent(summary: str, dtstart: str, dtend: str, uid: str, description: str = "") -> str:
    lines = [
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{_utcnow_stamp()}",
        f"DTSTART:{dtstart}",
        f"DTEND:{dtend}",
        f"SUMMARY:{_escape(summary)}",
    ]
    if description:
        lines.append(f"DESCRIPTION:{_escape(description)}")
    lines.append("END:VEVENT")
    return "\r\n".join(lines)


def build_ical(event) -> str:
    """Build a VCALENDAR string for the given EventState."""
    vevents = []

    if event.confirmed_date and event.confirmed_date != "TBD":
        # Single confirmed event
        try:
            dt = datetime.fromisoformat(event.confirmed_date)
            dtstart = _to_ical_dt(dt)
            dtend = _to_ical_dt(dt + timedelta(hours=1))
            vevents.append(_vevent(
                summary=event.event_name,
                dtstart=dtstart,
                dtend=dtend,
                uid=f"{event.event_id}@overlap.bot",
                description=f"Organized by {event.organizer_cname}",
            ))
        except ValueError:
            logger.warning(f"Could not parse confirmed_date for export: {event.confirmed_date}")
    else:
        # All proposed slots
        for i, slot in enumerate(sorted(event.slots)):
            try:
                dt = datetime.fromisoformat(slot)
                dtstart = _to_ical_dt(dt)
                dtend = _to_ical_dt(dt + timedelta(hours=1))
                slot_uid = f"{event.event_id}-slot{i}@overlap.bot"
                rsvp_count = len(event.availability.get(slot, {}))
                vevents.append(_vevent(
                    summary=f"{event.event_name} (proposed)",
                    dtstart=dtstart,
                    dtend=dtend,
                    uid=slot_uid,
                    description=f"Proposed slot — {rsvp_count} available. Organized by {event.organizer_cname}",
                ))
            except ValueError:
                logger.warning(f"Skipping malformed slot in export: {slot}")

    if not vevents:
        return ""

    cal_lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Overlap//Event Bot//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
    ] + vevents + ["END:VCALENDAR"]

    return "\r\n".join(cal_lines)


async def export_event(interaction: discord.Interaction, event_name: str):
    """Handler for /export command."""
    await interaction.response.defer(ephemeral=True, thinking=True)

    matches = events.get_events(interaction.guild_id, event_name)
    if not matches:
        await interaction.followup.send(f"❌ No event found matching `{event_name}`.", ephemeral=True)
        return

    if len(matches) > 1:
        names = ", ".join(f"`{n}`" for n in matches.keys())
        await interaction.followup.send(
            f"😬 Multiple events matched. Be more specific:\n{names}", ephemeral=True
        )
        return

    event = list(matches.values())[0]
    ical_str = build_ical(event)

    if not ical_str:
        await interaction.followup.send(
            "❌ No dates to export — add time slots first.", ephemeral=True
        )
        return

    file_bytes = ical_str.encode("utf-8")
    safe_name = "".join(c if c.isalnum() or c in "-_ " else "_" for c in event.event_name).strip()
    filename = f"{safe_name}.ics"

    discord_file = discord.File(io.BytesIO(file_bytes), filename=filename)

    status = "confirmed date" if (event.confirmed_date and event.confirmed_date != "TBD") else f"{len(event.slots)} proposed slots"
    await interaction.followup.send(
        f"📅 **{event.event_name}** — {status}\nImport this file into Google Calendar, Apple Calendar, or Outlook.",
        file=discord_file,
        ephemeral=True,
    )
