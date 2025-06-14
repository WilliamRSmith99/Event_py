import pytz, discord
from typing import Optional
from datetime import datetime, timezone
from core import storage
from collections import defaultdict

# ========== Time Conversion Utilities ==========
def to_utc_isoformat(datetime_str: str, user_timezone: str) -> str:
    """
    Convert a local user time string to UTC ISO format.
    """
    local_tz = pytz.timezone(user_timezone)
    try:
        naive = datetime.strptime(datetime_str, "%A, %m/%d/%y at %I%p")
        localized = local_tz.localize(naive)
        return localized.astimezone(pytz.utc).isoformat()  # Convert to UTC and return ISO format
    except Exception as e:
        print(f"Error in to_utc_isoformat: {e}")
        return datetime_str  # Return the original string if an error occurs

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
        print(f"[parse_utc_availability_key] Invalid datetime: {combined} - {e}")
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