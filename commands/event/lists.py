from discord.ui import Button
from datetime import timedelta,datetime
from commands.user import timezone
from core import auth, events, utils, userdata, conf, bulletins
from commands.event import register, responses, manage
import discord

# --- Event Rendering ---
def format_discord_timestamp(iso_str: str) -> str:
    """Return a Discord full timestamp (<t:...:f>) from UTC ISO string."""
    dt = datetime.fromisoformat(iso_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return f"<t:{int(dt.timestamp())}:f>"

def group_consecutive_hours_timestamp(availability: dict) -> list[str]:
    """
    Groups adjacent 1-hour UTC slots from event_data.availability.
    Returns strings showing full Discord timestamps with RSVP counts.
    """
    if not availability:
        return []

    # Sort by UTC datetime
    sorted_slots = sorted(
        [(datetime.fromisoformat(ts), ts, len(users)) for ts, users in availability.items()],
        key=lambda x: x[0]
    )

    output = []
    start_dt, start_ts, max_rsvp = sorted_slots[0]
    end_dt = start_dt + timedelta(hours=1)
    end_ts = start_ts

    for i in range(1, len(sorted_slots)):
        current_dt, current_ts, rsvp_count = sorted_slots[i]
        next_end = current_dt + timedelta(hours=1)

        if current_dt <= end_dt + timedelta(minutes=5):  # allow small overlap
            end_dt = next_end
            end_ts = current_ts
            max_rsvp = max(max_rsvp, rsvp_count)
        else:
            output.append(
                f"{format_discord_timestamp(start_ts)} -> {format_discord_timestamp(end_ts)} (RSVPs: {max_rsvp})"
            )
            start_dt, start_ts, max_rsvp = current_dt, current_ts, rsvp_count
            end_dt = next_end
            end_ts = current_ts

    # Final range
    output.append(
        f"{format_discord_timestamp(start_ts)} -> {format_discord_timestamp(end_ts)} (RSVPs: {max_rsvp})"
    )

    return output

async def handle_event_message(interaction, event, context="followup", inherit_view=None, server_config=None):
    """
    Handle sending or editing an event message. Supports followup, edit, and bulletin contexts.

    Args:
        interaction (discord.Interaction): The interaction from the user.
        event (EventData): Event object containing event details.
        context (str): Context for the message ("followup", "edit", or "bulletin").
        inherit_view (discord.ui.View): Optional inherited view to use for buttons.
        server_config (ServerConfig): Optional server config for bulletin channels.
    """
    user_tz = userdata.get_user_timezone(interaction.user.id)
    event_data = events.get_event_by_id(interaction.guild.id, event.event_id)
    if not user_tz or context == "bulletin":
        user_tz = "*Your local time*"
        
    if event_data.confirmed_dates != "TBD" and event_data.confirmed_dates != None :
        confirmed_availability = { f"{iso_str}" : event_data.availability.get(f"{iso_str}", {}) for iso_str in event_data.confirmed_dates}    
        confirmed_dates = "\n".join(f"• {d}" for d in group_consecutive_hours_timestamp(confirmed_availability))
    proposed_dates = "\n".join(f"• {d}" for d in group_consecutive_hours_timestamp(event_data.availability))
    body = (
        f"📅 **Event:** `{event.event_name}`\n"
        f"🙋 **Organizer:** <@{event.organizer}>\n"
        f"✅ **Confirmed Date:** *{confirmed_dates or 'TBD'}*\n"
        f"🗓️ **Proposed Dates ({user_tz}):**\n{proposed_dates or '*None yet*'}\n"
    )

    
    if inherit_view:
        view = inherit_view
    else:
        view = EventView(event, context, is_selected=(str(interaction.user.id) in event.rsvp))

        if await auth.authenticate(interaction.user, event.organizer) or context=="bulletin":
            view.add_item(ManageEventButton(event, context=context))

    match context:
        case "edit":
            msg = await interaction.response.edit_message(content=body, view=view)
        case "followup":
            msg = await interaction.followup.send(content=body, ephemeral=True, view=view)
                
        case "bulletin":
            server_config = conf.get_config(interaction.guild.id)
            bulletin_channel = server_config.bulletin_channel
            channel = interaction.guild.get_channel(int(bulletin_channel))
            if not channel:
                await interaction.response.send_message("❌ Bulletin channel not found.", ephemeral=True)
                return
            event.bulletin_channel_id = str(bulletin_channel)

            bulletin_msg = await channel.send(content=body, view=view)
            event.bulletin_message_id = str(bulletin_msg.id)

            # Log bulletin and event updates
            bulletin = bulletins.BulletinMessageEntry(
                event=event.event_name,
                event_id=event.event_id,
                guild_id=event.guild_id,
                channel_id=server_config.bulletin_channel,
                msg_head_id=f"{bulletin_msg.id}"
            )

            events.modify_event(event)
            bulletins.modify_event_bulletin(guild_id=interaction.guild.id, entry=bulletin)
    return

async def event_info(interaction: discord.Interaction, event_name: str = None):
    """Displays upcoming events or a message if no events are found."""
    events_found = events.get_events_by_name(interaction.guild_id, event_name)

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
        await handle_event_message(interaction, event, context="followup")

class RegisterButton(Button):
    def __init__(self, event,context, is_selected: bool):
        self.event = event
        self.event_id = event.event_id
        self.context = context
        button_label = "Edit Registration" if is_selected else "🚀 Register"
        button_style = discord.ButtonStyle.danger if is_selected else discord.ButtonStyle.primary
        custom_id = f"register:{self.event_id}"
        super().__init__(label=button_label, style=button_style, custom_id=custom_id)

    async def callback(self, interaction: discord.Interaction):
        await register.schedule_command(interaction, self.event_id, self.context)

class InfoButton(Button):
    def __init__(self, event, context = "edit"):
        self.event = event
        self.event_name = event.event_name
        super().__init__(label="💡 Info", style=discord.ButtonStyle.secondary, custom_id=f"info:{self.event_name}")

    async def callback(self, interaction: discord.Interaction):
        event = events.get_event_by_id(self.event.guild_id, self.event.event_id)
        user_tz = userdata.get_user_timezone(interaction.user.id) or "Etc/UTC"
        if event.confirmed_dates:
            confirmed_availability = { f"{iso_str}" : event.availability.get(f"{iso_str}", {}) for iso_str in event.confirmed_dates}
            local_availability = utils.from_utc_to_local(confirmed_availability, user_tz)
        else:
            local_availability = utils.from_utc_to_local(event.availability, user_tz)
        view = responses.OverlapSummaryView(event, local_availability, user_tz, show_back_button=False)
        msg = await interaction.response.send_message(
            f"📊 Top availability slots for **{event.event_name}** ({user_tz})",
            view=view,
            ephemeral=True
        )
        view.message = msg 

class NotificationButton(Button):
    def __init__(self, event):
        self.event_name = event.event_name
        super().__init__(label="🔔 Notifications", style=discord.ButtonStyle.secondary, custom_id=f"notifications:{self.event_name}")

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_message("📅 Notifications for the event are set!", ephemeral=True)

class ManageEventButton(Button):
    def __init__(self, event, context = "edit"):
        self.event = event
        self.context = context
        self.event_name = event.event_name
        super().__init__(label="🛠️ Manage Event", style=discord.ButtonStyle.danger, custom_id=f"manage_event:{self.event_name}")

    async def callback(self, interaction: discord.Interaction):
        if not await auth.authenticate(interaction.user, self.event.organizer):
            await interaction.response.send_message("❌ You don’t have permission to manage this event.", ephemeral=True)
            return

        view = ManageEventView(self.event, self.context, interaction.guild.id, interaction.user)
        if self.context != "bulletin":
            await interaction.response.edit_message(
                view=view
            )
            view.message = interaction.message
        else:
            await interaction.response.send_message(f"Manage {self.event.event_name}:", view=view, ephemeral=True)            
            return

# --- View Definitions ---

class EventView(utils.ExpiringView):
    def __init__(self, event, context, is_selected=False):
        super().__init__(timeout=180 if not context == "bulletin" else None)
        if context == "bulletin":
            is_selected = False
        self.add_item(RegisterButton(event, context, is_selected))
        self.add_item(InfoButton(event, context))
        self.add_item(NotificationButton(event))
        

class ManageEventView(utils.ExpiringView):
    def __init__(self, event, context ,guild_id: int, user):
        super().__init__(timeout=180 if not context == "bulletin" else None)
        self.event = event
        self.context = context
        self.event_details = event
        self.guild_id = guild_id
        self.user = user

    # @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    # async def cancel_button(self, interaction: discord.Interaction, _):
    #     if not await auth.authenticate(interaction.user, self.event.organizer):
    #         await interaction.response.send_message("❌ You don’t have permission to view this event.", ephemeral=True)
    #         return

    #     is_selected = str(interaction.user.id) in self.event.rsvp
    #     view = EventView(self.event, self.context, is_selected=is_selected)
    #     view.add_item(NotificationButton(self.event))

    #     if await auth.authenticate(self.user, self.event.organizer):
    #         view.add_item(ManageEventButton(self.event,context=self.context))
        
    #     if self.context == "bulletin":
    #         await interaction.response.edit_message(content=f"❌ Cancelled", view=None)
    #         view.message = interaction.message
    #         return
        
    #     await interaction.response.edit_message(view=view)
    #     view.message = interaction.message
    #     return
        
            
    @discord.ui.button(label="Edit Event", style=discord.ButtonStyle.primary)
    async def edit_button(self, interaction: discord.Interaction, _):
        await interaction.response.send_message("🔧 Edit Event functionality coming soon!", ephemeral=True)

    @discord.ui.button(label="Confirm Datetime", style=discord.ButtonStyle.success)
    async def confirm_button(self, interaction: discord.Interaction, _):
        await manage.handle_confirm_dates(interaction, self.event.event_id, "local")

    @discord.ui.button(label="Delete", style=discord.ButtonStyle.danger)
    async def delete_button(self, interaction: discord.Interaction, _):
        if not await auth.authenticate(interaction.user, self.event.organizer):
            await interaction.response.send_message("❌ You don’t have permission to delete this event.", ephemeral=True)
            return

        await manage._prompt_event_deletion(
            interaction,
            self.guild_id,
            self.event_details,
            return_on_cancel= await handle_event_message(interaction, self.event_details, "edit") if not self.context == "bulletin" else None
        )
