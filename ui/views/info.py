from discord.ui import Button
from core import auth, events
from commands.events import register, manage, info
from ui.views import base, responses
import discord

# --- Custom Button Implementations ---

class RegisterButton(Button):
    def __init__(self, event, is_selected: bool):
        self.event = event
        self.event_name = event.event_name
        button_label = "Edit Registration" if is_selected else "Register"
        button_style = discord.ButtonStyle.danger if is_selected else discord.ButtonStyle.primary
        custom_id = f"register:{self.event_name}"
        super().__init__(label=button_label, style=button_style, custom_id=custom_id)

    async def callback(self, interaction: discord.Interaction):
        await register.schedule_command(interaction, self.event_name)

class InfoButton(Button):
    def __init__(self, event):
        self.event = event
        self.event_name = event.event_name
        super().__init__(label="Info", style=discord.ButtonStyle.secondary, custom_id=f"info:{self.event_name}")

    async def callback(self, interaction: discord.Interaction):
        event = events.get_event(interaction.guild.id, self.event_name)
        if not event:
            await interaction.response.send_message("⚠️ Event data missing.", ephemeral=True)
            return

        view = responses.OverlapSummaryView(event, show_back_button=True)
        msg = await interaction.response.edit_message(
            content=f"📊 Top availability slots for **{event.event_name}**",
            view=view
        )
        view.message = msg  # Optional if you want expiry cleanup on info view

class NotificationButton(Button):
    def __init__(self, event):
        self.event_name = event.event_name
        super().__init__(label="🔔 Notifications", style=discord.ButtonStyle.secondary, custom_id=f"notifications:{self.event_name}")

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_message("📅 Notifications for the event are set!", ephemeral=True)

class ManageEventButton(Button):
    def __init__(self, event):
        self.event = event
        self.event_name = event.event_name
        super().__init__(label="Manage Event", style=discord.ButtonStyle.danger, custom_id=f"manage_event:{self.event_name}")

    async def callback(self, interaction: discord.Interaction):
        if not await auth.authenticate(interaction.user, self.event.organizer):
            await interaction.response.send_message("❌ You don’t have permission to manage this event.", ephemeral=True)
            return

        view = ManageEventView(self.event, interaction.guild.id, interaction.user)
        msg = await interaction.followup.send(
            content="🔧 Manage your event below:",
            ephemeral=True,
            view=view
        )
        view.message = msg

# --- View Definitions ---

class EventView(base.ExpiringView):
    def __init__(self, event, is_selected=False):
        super().__init__(timeout=180)
        self.add_item(RegisterButton(event, is_selected))
        self.add_item(InfoButton(event))

class ManageEventView(base.ExpiringView):
    def __init__(self, event, guild_id: int, user):
        super().__init__(timeout=180)
        self.event = event
        self.event_details = event  # Added to fix missing field in delete
        self.guild_id = guild_id
        self.user = user

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel_button(self, interaction: discord.Interaction, _):
        if not await auth.authenticate(interaction.user, self.event.organizer):
            await interaction.response.send_message("❌ You don’t have permission to view this event.", ephemeral=True)
            return

        is_selected = str(interaction.user.id) in self.event.rsvp
        view = EventView(self.event, is_selected=is_selected)

        if self.event.confirmed_date and self.event.confirmed_date != "TBD":
            view.add_item(NotificationButton(self.event))

        if await auth.authenticate(self.user, self.event.organizer):
            view.add_item(ManageEventButton(self.event))

        msg = await interaction.followup.send(content="✅ Back to event view:", ephemeral=True, view=view)
        view.message = msg

    @discord.ui.button(label="Edit Event", style=discord.ButtonStyle.primary)
    async def edit_button(self, interaction: discord.Interaction, _):
        await interaction.response.send_message("🔧 Edit Event functionality coming soon!", ephemeral=True)

    @discord.ui.button(label="Confirm Datetime", style=discord.ButtonStyle.success)
    async def confirm_button(self, interaction: discord.Interaction, _):
        await interaction.response.send_message("✅ Confirm Event Datetime functionality coming soon!", ephemeral=True)

    @discord.ui.button(label="Delete", style=discord.ButtonStyle.danger)
    async def delete_button(self, interaction: discord.Interaction, _):
        if not await auth.authenticate(interaction.user, self.event.organizer):
            await interaction.response.send_message("❌ You don’t have permission to delete this event.", ephemeral=True)
            return

        await manage._prompt_event_deletion(
            interaction,
            self.guild_id,
            self.event.event_name,
            self.event_details,
            return_on_cancel=info.manage_event_context
        )
