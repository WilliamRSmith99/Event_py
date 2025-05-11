import discord
import json
from database import user_data, shared
from pathlib import Path

# Path to the timezone data file
DATA_FILE = Path("commands/timezone/TZ.json")

# Load timezone data if file exists
if DATA_FILE.exists():
    with open(DATA_FILE, "r") as f:
        timeZoneReference = json.load(f)
else:
    raise FileNotFoundError(f"{DATA_FILE} not found. Please ensure the timezone data file exists.")

# Group timezones by region prefix (e.g., America, Europe)
def get_timezone_groups():
    """Group and return timezones by their region."""
    zones = sorted(tz for tz in timeZoneReference if "/" in tz)
    grouped = {}
    for tz in zones:
        region = tz.split("/")[0]
        grouped.setdefault(region, []).append(tz)
    return grouped

class TimezoneDropdown(discord.ui.Select):
    """Base class for time zone dropdowns (both select and reset)."""
    def __init__(self, user_id, region, interaction=None, reset=False):
        self.user_id = user_id
        self.region = region
        self.interaction = interaction
        self.reset = reset
        # Limit to 25 options for Discord's UI limit
        options = [
            discord.SelectOption(label=tz.split("/")[-1], value=tz)
            for tz in timeZoneReference[region][:25]
        ]
        placeholder = f"Select your timezone ({region})"
        super().__init__(placeholder=placeholder, options=options, custom_id=f"tz_{'reset' if reset else 'select'}_{user_id}_{region}")

    async def callback(self, interaction: discord.Interaction):
        """Callback for handling timezone selection or reset."""
        selected = self.values[0]
        user_data.set_user_timezone(interaction.user.id, selected)
        response_message = f"✅ Timezone set to `{selected}`"
        
        # Respond according to whether it's a reset or select operation
        if self.reset:
            await shared.safe_respond(interaction, response_message, ephemeral=True, view=None)
        else:
            await interaction.response.edit_message(content=response_message, view=None)

class RegionSelect(discord.ui.Select):
    """Region selection for time zone configuration."""
    def __init__(self, user_id):
        self.user_id = user_id
        regions = sorted(timeZoneReference.keys())
        options = [
            discord.SelectOption(label=region, value=region)
            for region in regions[:25]
        ]
        super().__init__(placeholder="Select a timezone region", options=options)

    async def callback(self, interaction: discord.Interaction):
        """Handle region selection and prompt user for time zone."""
        region = self.values[0]
        await interaction.response.edit_message(
            content=f"Now select your timezone from {region}:",
            view=TimezonePickerView(self.user_id, region)
        )

class RegionSelectView(discord.ui.View):
    """View that allows users to select a region."""
    def __init__(self, user_id):
        super().__init__(timeout=60)
        self.add_item(RegionSelect(user_id))

class TimezonePickerView(discord.ui.View):
    """View that allows users to select their timezone."""
    def __init__(self, user_id, region):
        super().__init__(timeout=60)
        self.add_item(TimezoneDropdown(user_id, region))

class TimezoneResetView(discord.ui.View):
    """View that allows users to reset their timezone."""
    def __init__(self, user_id, timeout=60):
        super().__init__(timeout=timeout)
        self.add_item(TimezoneDropdown(user_id, region=None, reset=True))

