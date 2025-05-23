import pytz, discord
from typing import Optional
from datetime import datetime
from core import storage

# ========== Time Conversion Utilities ==========
def to_utc_isoformat(datetime_str: str, user_timezone: str) -> str:
    """
    Convert a local user time string to UTC ISO format.
    """
    local_tz = pytz.timezone(user_timezone)
    naive = datetime.strptime(datetime_str, "%A, %m/%d/%y at %I%p")
    localized = local_tz.localize(naive)
    return localized.astimezone(pytz.utc).isoformat()


def from_utc_to_local(utc_date_str: str, user_timezone: str) -> str:
    """
    Convert a UTC time string to a user's local time in ISO format.
    """
    try:
        naive_utc = datetime.strptime(utc_date_str, "%A, %m/%d/%y at %I%p")
        user_tz = pytz.timezone(user_timezone)
        normalized = pytz.utc.localize(naive_utc)
        return normalized.astimezone(user_tz).isoformat()
    except Exception as e:
        print(f"[from_utc_to_local] Error: {e}")
        return utc_date_str


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