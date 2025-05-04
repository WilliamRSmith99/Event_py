import discord, json
from database import user_data, shared

from pathlib import Path

DATA_FILE = Path("commands/timezone/TZ.json")

if DATA_FILE.exists():
    with open(DATA_FILE, "r") as f:
        timeZoneReference = json.load(f)

# Group timezones by region prefix (e.g., America, Europe)
def get_timezone_groups():
    zones = sorted(tz for tz in timeZoneReference if "/" in tz)
    grouped = {}
    for tz in zones:
        region = tz.split("/")[0]
        grouped.setdefault(region, []).append(tz)
    return grouped

class TimezoneReset(discord.ui.Select):
    def __init__(self, user_id,  interaction: discord.Interaction, region: str):
        self.user_id = user_id
        self.interaction = interaction
        options = [
            discord.SelectOption(label=tz.split("/")[-1], value=tz)
            for tz in timeZoneReference[region][:25]  # Discord max
        ]
        super().__init__(placeholder=f"Select your timezone ({region})", options=options, custom_id=f"tz_reset_{user_id}_{region}")

    async def callback(self, interaction: discord.Interaction):
        selected = self.values[0]
        user_data.set_user_timezone(interaction.user.id, selected)
        await shared.safe_respond(interaction, f"✅ Timezone set to `{selected}`", ephemeral=True, view=None)
        # await interaction.response.send_message(f"✅ Timezone set to `{selected}`", ephemeral=True)

class TimezoneSelect(discord.ui.Select):
    def __init__(self, user_id, region: str):
        self.user_id = user_id
        options = [
            discord.SelectOption(label=tz.split("/")[-1], value=tz)
            for tz in timeZoneReference[region][:25]  # Discord max
        ]
        super().__init__(placeholder=f"Select your timezone ({region})", options=options, custom_id=f"tz_select_{user_id}_{region}")

    async def callback(self, interaction: discord.Interaction):
        selected = self.values[0]
        user_data.set_user_timezone(interaction.user.id, selected)
        # await shared.safe_respond(interaction, f"✅ Timezone set to `{selected}`", ephemeral=True, view=None)
        await interaction.response.edit_message( content=f"✅ Timezone set to `{selected}`", view=None)

class RegionSelect(discord.ui.Select):
    def __init__(self, user_id):
        self.user_id = user_id
        regions = sorted(timeZoneReference.keys())
        options = [
            discord.SelectOption(label=region, value=region)
            for region in regions[:25]
        ]
        super().__init__(placeholder="Select a timezone region", options=options)

    async def callback(self, interaction: discord.Interaction):
        region = self.values[0]
        await interaction.response.edit_message(
            content=f"Now select your timezone from {region}:",
            view=TimezonePickerView(self.user_id, region)
        )
        # await shared.safe_respond(interaction,  f"Now select your timezone from {region}:", ephemeral=True, view=TimezonePickerView(self.user_id, region),)


class RegionSelectView(discord.ui.View):
    def __init__(self, user_id):
        super().__init__(timeout=60)
        self.add_item(RegionSelect(user_id))

class TimezonePickerView(discord.ui.View):
    def __init__(self, user_id, region):
        super().__init__(timeout=60)
        self.add_item(TimezoneSelect(user_id, region))

class TimezoneResetView(discord.ui.View):
    def __init__(self, user_id, timeout = 60):
        super().__init__(timeout=timeout)
        self.add_item(TimezoneReset(user_id))