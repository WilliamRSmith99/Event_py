import discord
from discord.ui import View, Button
from commands.user import timezone
from core import userdata

class UserSettingsView(View):
    def __init__(self, user_id, guild_id):
        super().__init__(timeout=180)
        self.user_id = user_id
        self.guild_id = guild_id
        self.add_item(SetTimezoneButton(user_id))
        self.add_item(TimeFormatButton(user_id, guild_id))


class SetTimezoneButton(Button):
    def __init__(self, user_id):
        self.user_id = user_id
        super().__init__(label="Set Timezone", style=discord.ButtonStyle.primary)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This is not your settings menu.", ephemeral=True)
            return

        await interaction.response.send_message(
            "🌍 Select your timezone region:",
            view=timezone.RegionSelectView(self.user_id),
            ephemeral=True
        )


class TimeFormatButton(Button):
    def __init__(self, user_id, guild_id):
        self.user_id = user_id
        self.guild_id = guild_id

        # Get current effective format
        user_pref = userdata.get_user_time_format(user_id)

        if user_pref is None:
            # Using server default
            from core import conf
            server_config = conf.get_config(guild_id)
            server_24hr = getattr(server_config, "use_24hr_time", False) if server_config else False
            label = f"🕐 Using server default ({'24hr' if server_24hr else '12hr'})"
            style = discord.ButtonStyle.secondary
        elif user_pref:
            label = "🕐 24-hour format (13:00)"
            style = discord.ButtonStyle.primary
        else:
            label = "🕐 12-hour format (1:00 PM)"
            style = discord.ButtonStyle.primary

        super().__init__(label=label, style=style)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This is not your settings menu.", ephemeral=True)
            return

        # Cycle through: server default -> 12hr -> 24hr -> server default
        user_pref = userdata.get_user_time_format(self.user_id)

        if user_pref is None:
            # Currently server default -> switch to 12hr
            userdata.set_user_time_format(self.user_id, False)
        elif not user_pref:
            # Currently 12hr -> switch to 24hr
            userdata.set_user_time_format(self.user_id, True)
        else:
            # Currently 24hr -> switch to server default
            userdata.clear_user_time_format(self.user_id)

        # Refresh the view
        view = UserSettingsView(self.user_id, self.guild_id)
        content = _build_settings_content(self.user_id, self.guild_id)
        await interaction.response.edit_message(content=content, view=view)

def _build_settings_content(user_id: int, guild_id: int) -> str:
    """Build the settings display content."""
    current_tz = userdata.get_user_timezone(user_id)
    user_time_pref = userdata.get_user_time_format(user_id)

    content = "⚙️ **Your Personal Settings**\n\n"

    # Timezone
    if current_tz:
        content += f"🌍 **Timezone:** `{current_tz}`\n"
    else:
        content += "🌍 **Timezone:** *Not set*\n"

    # Time format
    if user_time_pref is None:
        from core import conf
        server_config = conf.get_config(guild_id)
        server_24hr = getattr(server_config, "use_24hr_time", False) if server_config else False
        content += f"🕐 **Time Format:** Using server default ({'24-hour' if server_24hr else '12-hour'})\n"
    elif user_time_pref:
        content += "🕐 **Time Format:** 24-hour (13:00)\n"
    else:
        content += "🕐 **Time Format:** 12-hour (1:00 PM)\n"

    return content


async def user_settings(interaction: discord.Interaction):
    """Command to show user-specific settings."""
    user_id = interaction.user.id
    guild_id = interaction.guild_id

    content = _build_settings_content(user_id, guild_id)
    view = UserSettingsView(user_id, guild_id)
    await interaction.response.send_message(content, view=view, ephemeral=True)
