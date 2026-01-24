from discord.ui import Button, View
import discord
from commands.event import register
from commands.user import notifications as notif_commands
from core.emojis import EMOJIS_MAP
from core.bulletins import handle_slot_selection
from core.parsers import extract_event_name_from_bulletin


class GlobalBulletinView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Register", style=discord.ButtonStyle.primary, custom_id="bulletin:register")
    async def register(self, interaction: discord.Interaction, button: Button):
        event_name = extract_event_name_from_bulletin(interaction.message.content)
        if not event_name:
            return await interaction.response.send_message("Could not find the event name in the bulletin.", ephemeral=True)
        await register.schedule_command(interaction, event_name, eph_resp=True)

    @discord.ui.button(label="Notify Me", style=discord.ButtonStyle.secondary, custom_id="bulletin:notify")
    async def notify(self, interaction: discord.Interaction, button: Button):
        event_name = extract_event_name_from_bulletin(interaction.message.content)
        if not event_name:
            return await interaction.response.send_message("Could not find the event name in the bulletin.", ephemeral=True)
        await notif_commands.show_notification_settings(interaction, event_name)


class GlobalThreadView(View):
    def __init__(self, event_name: str, slots: list[tuple[str, str]]):
        super().__init__(timeout=None)
        for emoji, slot in slots:
            self.add_item(Button(label=f"Register {emoji}", style=discord.ButtonStyle.primary, custom_id=f"thread:register_slot:{slot}"))

    @discord.ui.button(label="Register Slot", style=discord.ButtonStyle.primary, custom_id="thread:register_slot")
    async def register_slot(self, interaction: discord.Interaction, button: Button):
        
        event_name = extract_event_name_from_bulletin(interaction.message.content)
        if not event_name:
            # Fallback to parsing from the embed title
            if interaction.message.embeds:
                title = interaction.message.embeds[0].title
                if title:
                    # Assuming title is "🗓️ Event Signup – EVENT_NAME"
                    parts = title.split("–")
                    if len(parts) > 1:
                        event_name = parts[1].strip()

        if not event_name:
            return await interaction.response.send_message("Could not find the event name.", ephemeral=True)

        # The slot is in the custom_id of the button that was clicked.
        # The format is "register:EVENT_NAME:SLOT_TIME"
        # We can get it from the interaction's data
        custom_id = interaction.data["custom_id"]
        try:
            slot_time = custom_id.split(":")[-1]
        except (IndexError, ValueError):
            return await interaction.response.send_message("Invalid slot selection.", ephemeral=True)


        await interaction.response.defer(ephemeral=True)

        await handle_slot_selection(
            interaction=interaction,
            event_name=event_name,
            selected_slot=slot_time
        )
