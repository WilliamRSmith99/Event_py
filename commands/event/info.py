from commands import register, view_responses
from discord.ui import View, Button
from datetime import datetime
from database import events, user_data, shared
from commands.timezone import timezone
import discord

class RegisterButton(Button):
    """Button to either register or edit registration for an event."""
    def __init__(self, event, is_selected: bool):
        self.event = event
        self.event_name = event.event_name
        button_label = "Edit Registration" if is_selected else "Register"
        button_style = discord.ButtonStyle.danger if is_selected else discord.ButtonStyle.primary
        custom_id = f"register:{self.event_name}"

        super().__init__(label=button_label, style=button_style, custom_id=custom_id)

    async def callback(self, interaction: discord.Interaction):
        """Handles event registration logic."""
        await register.schedule_command(interaction, self.event_name)

class InfoButton(Button):
    """Button to display event info."""
    def __init__(self, event):
        self.event = event
        self.event_name = event.event_name
        super().__init__(label="Info", style=discord.ButtonStyle.secondary, custom_id=f"Info:{self.event_name}")

    async def callback(self, interaction: discord.Interaction):
        """Handles event information display."""
        event_name = self.event_name
        if not event_name:
            return None, "❌ Event not found."

        event = events.get_event(interaction.guild.id, event_name)
        if not event:
            return None, "⚠️ Event data missing."

        view = view_responses.OverlapSummaryView(event, show_back_button=True)
        
        await interaction.response.edit_message(
            content=f"📊 Top availability slots for **{event.event_name}**", 
            view=view
        )

class EventView(View):
    """View for displaying the register and info buttons for an event."""
    def __init__(self, event, is_selected=False):
        super().__init__(timeout=None)
        self.add_item(RegisterButton(event, is_selected=is_selected))  
        self.add_item(InfoButton(event))  

class InfoView(View):
    """View for displaying the register button only."""
    def __init__(self, event, is_selected=False):
        super().__init__(timeout=None)
        self.add_item(RegisterButton(event, is_selected=is_selected))

async def upcomingevents(interaction: discord.Interaction, event_name: str = None):
    """Displays upcoming events or a message if no events are found."""
    events_found = events.get_events(interaction.guild_id, event_name)

    if not events_found:
        message = (
            f"❌ No Events found for `{event_name}`." 
            if event_name 
            else "📅 No upcoming events.\n\n\n 🤫 *psst*: create new events with `/newevent`"
        )
        await interaction.response.send_message(message, ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True, thinking=True)

    for event in events_found.values():
        await format_single_event(interaction, event, is_edit=False)

async def format_single_event(interaction, event, is_edit=False):
    """Formats and displays a single event with user availability."""
    user_tz = user_data.get_user_timezone(interaction.user.id)
    if not user_tz:
        await shared.safe_respond(
            interaction,
            "❌ Oh no! We can't find you!\n\nSelect your timezone to register new events:",
            ephemeral=True,
            view=timezone.RegionSelectView(interaction.user.id)
        )
        return

    local_dates = set()
    user_availability = event.availability
    is_selected = str(interaction.user.id) in event.rsvp

    for date_str, hours in user_availability.items():
        for hour in hours:
            utc_key = f"{date_str} at {hour}"
            local_date = (datetime.fromisoformat(events.from_utc_to_local(utc_key, user_tz))).strftime("%A, %m/%d/%y")
            local_dates.add(local_date)

    proposed_dates = "\n".join(f"• {d}" for d in sorted(local_dates))

    body = (
        f"📅 **Event:** `{event.event_name}`\n"
        f"🙋 **Organizer:** <@{event.organizer}>\n"
        f"✅ **Confirmed Date:** *{event.confirmed_date or 'TBD'}*\n"
        f"🗓️ **Proposed Dates (Your Timezone - `{user_tz}`):**\n{proposed_dates or '*None yet*'}\n"
    )

    view = EventView(event, is_selected=is_selected)

    if is_edit:
        await interaction.response.edit_message(content=body, view=view)
    else:
        await interaction.followup.send(content=body, ephemeral=True, view=view)

