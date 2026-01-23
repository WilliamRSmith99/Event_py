import pytz, discord
from typing import Optional
from datetime import datetime, timezone
from core import storage
from core.logging import get_logger
from collections import defaultdict

logger = get_logger(__name__)

# ========== Time Conversion Utilities ==========
def to_utc_isoformat(datetime_str: str, user_timezone: str) -> str:
    """
    Convert a local user time string to UTC ISO format.

    Supports formats:
    - "Monday, 01/23/26 at 12:00 PM" (new format with :00 and space)
    - "Monday, 01/23/26 at 12PM" (legacy format)
    """
    local_tz = pytz.timezone(user_timezone)

    # Try multiple formats for flexibility
    formats = [
        "%A, %m/%d/%y at %I:%M %p",  # New format: "Monday, 01/23/26 at 12:00 PM"
        "%A, %m/%d/%y at %I %p",      # Format with space: "Monday, 01/23/26 at 12 PM"
        "%A, %m/%d/%y at %I%p",       # Legacy format: "Monday, 01/23/26 at 12PM"
    ]

    for fmt in formats:
        try:
            naive = datetime.strptime(datetime_str, fmt)
            localized = local_tz.localize(naive)
            return localized.astimezone(pytz.utc).isoformat()
        except ValueError:
            continue

    logger.warning(f"Error converting to UTC - no format matched: {datetime_str}")
    return datetime_str


from collections import defaultdict
from datetime import datetime
import pytz

def from_utc_to_local(availability, user_timezone: str) -> list:
    """
    Convert UTC time strings to user's local time, grouped and sorted by local date.
    
    Returns a list of (date_str, slots) tuples, sorted chronologically.
    Each slot is a tuple: (original_utc, local_date, users)
    """
    grouped = defaultdict(list)
    user_tz = pytz.timezone(user_timezone)

    for utc_time_str, users in availability.items():
        utc_dt = datetime.fromisoformat(utc_time_str)  # naive or UTC-aware
        if utc_dt.tzinfo is None:
            utc_dt = pytz.utc.localize(utc_dt)

        local_dt = utc_dt.astimezone(user_tz)
        date_key = local_dt.strftime("%A, %m/%d/%y")

        # Store (local datetime object, original UTC ISO string, users)
        grouped[date_key].append((local_dt, utc_time_str, users))

    # Sort by actual date (using local_dt)
    sorted_output = []
    for date_key in sorted(grouped.keys(), key=lambda d: datetime.strptime(d, "%A, %m/%d/%y")):
        day_slots = sorted(grouped[date_key], key=lambda x: x[0])  # sort by local_dt
        sorted_output.append((date_key, day_slots))

    return sorted_output

def parse_utc_availability_key(utc_date_str: str, utc_hour_str: str) -> Optional[datetime]:
    """
    Parse UTC date and hour strings into a timezone-aware UTC datetime.
    """
    try:
        combined = f"{utc_date_str} {utc_hour_str.upper()}"
        naive = datetime.strptime(combined, "%A, %m/%d/%y %I%p")
        return pytz.utc.localize(naive)
    except ValueError as e:
        logger.warning(f"Invalid datetime format: {combined}", exc_info=e)
        return None

def to_discord_timestamp(dt: datetime, style: str = 't') -> str:
    """
    Convert a datetime object to a Discord-formatted timestamp string.
    :param dt: naive or aware datetime object (UTC assumed if naive).
    :param style: Discord timestamp style: t, T, d, D, f, F, R
    :return: string like <t:1629072000:t>
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    unix_ts = int(dt.timestamp())
    return f"<t:{unix_ts}:{style}>"


def format_time(dt: datetime, use_24hr: bool = False, include_date: bool = False) -> str:
    """
    Format a datetime for display, respecting the time format preference.

    Args:
        dt: The datetime to format
        use_24hr: If True, use 24-hour format (13:00). If False, use 12-hour (1:00 PM)
        include_date: If True, include the date in the output

    Returns:
        Formatted time string
    """
    if use_24hr:
        time_fmt = "%H:%M"
    else:
        time_fmt = "%I:%M %p"

    if include_date:
        date_fmt = "%a %m/%d "
        return dt.strftime(date_fmt + time_fmt).lstrip("0")
    else:
        return dt.strftime(time_fmt).lstrip("0")


def format_time_range(start_dt: datetime, end_dt: datetime, use_24hr: bool = False) -> str:
    """
    Format a time range for display.

    Args:
        start_dt: Start datetime
        end_dt: End datetime
        use_24hr: If True, use 24-hour format

    Returns:
        Formatted range like "1:00 PM -> 3:00 PM" or "13:00 -> 15:00"
    """
    if use_24hr:
        return f"{start_dt.strftime('%H:%M')} -> {end_dt.strftime('%H:%M')}"
    else:
        return f"{start_dt.strftime('%I%p').lower()} -> {end_dt.strftime('%I%p').lower()}"


def format_hour(dt: datetime, use_24hr: bool = False) -> str:
    """
    Format just the hour for display (no minutes).

    Args:
        dt: The datetime
        use_24hr: If True, use 24-hour format

    Returns:
        Formatted hour like "1 PM" or "13:00"
    """
    if use_24hr:
        return dt.strftime("%H:%M")
    else:
        return dt.strftime("%-I %p")
        
def get_timezone_groups():
    """Group and return timezones by their region."""
    timeZoneReference = storage.read_json("timezone_data.json")
    zones = sorted(tz for tz in timeZoneReference if "/" in tz)
    grouped = {}
    for tz in zones:
        region = tz.split("/")[0]
        grouped.setdefault(region, []).append(tz)
    return grouped

async def safe_send(interaction: discord.Interaction, content: str, view: Optional[discord.ui.View] = None):
    if interaction.response.is_done():
        await interaction.edit_original_response(content=content, view=view)
    else:
        await interaction.response.send_message(content=content, view=view, ephemeral=True)

class ExpiringView(discord.ui.View):
    def __init__(self, *, timeout=180):
        super().__init__(timeout=timeout)
        self.message = None  # Reference to the sent message (ephemeral or otherwise)

    async def on_timeout(self):
        # Ephemeral messages can't be deleted, but can be edited to a minimal state
        if self.message:
            try:
                await self.message.edit(content="⏱️ This interaction has expired.", view=None)
            except discord.NotFound:
                pass