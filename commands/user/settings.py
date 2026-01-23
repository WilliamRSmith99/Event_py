import discord
from discord.ui import View, Button
from commands.user import timezone
from core import userdata

class UserSettingsView(View):
    def __init__(self, user_id):
        super().__init__(timeout=180)
        self.user_id = user_id
        self.add_item(SetTimezoneButton(user_id))


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

async def user_settings(interaction: discord.Interaction):
    """Command to show user-specific settings."""
    user_id = interaction.user.id
    current_tz = userdata.get_user_timezone(user_id)
    
    content = "Your personal settings for the Event Bot.\n\n"
    if current_tz:
        content += f"**Current Timezone:** `{current_tz}`"
    else:
        content += "**Current Timezone:** Not set."
        
    view = UserSettingsView(user_id)
    await interaction.response.send_message(content, view=view, ephemeral=True)
