from commands import register, view_responses
from discord.ui import View, Button
from datetime import datetime
from database import events, user_data,shared
from commands.timezone import timezone
import discord


class RegisterButton(Button):
    def __init__(self, event, is_selected: bool):
        self.event = event
        self.event_name = event.event_name
        super().__init__(
            label="Edit Registration" if is_selected else "Register",
            style=discord.ButtonStyle.danger  if is_selected else discord.ButtonStyle.primary,
            custom_id=f"register:{self.event_name}"
        )

    async def callback(self, interaction: discord.Interaction):
        # This is where you would handle the registration logic
        await register.schedule_command(interaction, self.event_name)
        
class InfoButton(Button):
    def __init__(self, event):
        self.event = event
        self.event_name = event.event_name
        super().__init__(
            label="Info",
            style=discord.ButtonStyle.secondary,
            custom_id=f"Info:{self.event_name}"
        )

    async def callback(self, interaction: discord.Interaction):
        full_event_name = events.resolve_event_name(interaction.guild.id, self.event_name)
        if not full_event_name:
            return None, "❌ Event not found."

        event = events.get_event(interaction.guild.id, full_event_name)
        if not event:
            return None, "⚠️ Event data missing."

        view = view_responses.OverlapSummaryView(event, show_back_button=True)
        event = events.get_event(interaction.guild.id, full_event_name)
        
        await interaction.response.edit_message(
            content=f"📊 Top availability slots for **{event.event_name}**", 
            view=view
        )
        # await view_responses.build_overlap_summary(interaction, self.event_name, interaction.guild_id)

class EventView(View):
    def __init__(self, event, is_selected=False):
        super().__init__(timeout=None)
        self.add_item(RegisterButton(event, is_selected=is_selected))  
        self.add_item(InfoButton(event))  
        
class InfoView(View):
    def __init__(self, event, is_selected=False):
        super().__init__(timeout=None)
        self.add_item(RegisterButton(event, is_selected=is_selected))  
 
async def upcomingevents(interaction: discord.Interaction, event_name:str=None):
    
    if event_name:
        full_event_name = events.resolve_event_name(interaction.guild_id, event_name)
        event = events.get_event(interaction.guild_id, full_event_name)
        if not event:
            await interaction.response.send_message("❌ Event not found.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        await format_single_event(interaction, event, is_edit=False)
    else:
        all_events = events.get_all_events(interaction.guild_id)
        if len(all_events) == 0:
            await interaction.response.send_message(
                "📅 No upcoming events.\n\n\n 🤫 *psst*: create new events with `/newevent`",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        for _, event in all_events.items():
            await format_single_event(interaction, event, is_edit=False)
        
async def format_single_event(interaction, event, is_edit=False):
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
        
        
        