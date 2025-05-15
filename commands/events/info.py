from discord.ui import Button
from datetime import datetime
from core import auth, events, user_state,utils
from commands.events import register, responses
from ui.views import base, timezone,info
import discord

# --- Event Rendering ---

async def manage_event_context(interaction: discord.Interaction, event_details: events.EventState):
    await format_single_event(interaction, event_details)

async def format_single_event(interaction, event, is_edit=False, inherit_view=None):
    user_tz = user_state.get_user_timezone(interaction.user.id)
    if not user_tz:
        view = timezone.RegionSelectView(interaction.user.id)
        msg = await utils.safe_respond(
            interaction,
            "❌ Oh no! We can't find you!\n\nSelect your timezone to register new events:",
            ephemeral=True,
            view=view
        )
        view.message = msg
        return

    local_dates = set()
    for date_str, hours in event.availability.items():
        for hour in hours:
            utc_key = f"{date_str} at {hour}"
            local_date = datetime.fromisoformat(utils.from_utc_to_local(utc_key, user_tz)).strftime("%A, %m/%d/%y")
            local_dates.add(local_date)

    proposed_dates = "\n".join(f"• {d}" for d in sorted(local_dates))
    body = (
        f"📅 **Event:** `{event.event_name}`\n"
        f"🙋 **Organizer:** <@{event.organizer}>\n"
        f"✅ **Confirmed Date:** *{event.confirmed_date or 'TBD'}*\n"
        f"🗓️ **Proposed Dates (Your Timezone - `{user_tz}`):**\n{proposed_dates or '*None yet*'}\n"
    )

    if inherit_view:
        view = inherit_view
    else:
        view = info.EventView(event, is_selected=(str(interaction.user.id) in event.rsvp))

    if event.confirmed_date and event.confirmed_date != "TBD":
        view.add_item(info.NotificationButton(event))

    if await auth.authenticate(interaction.user, event.organizer):
        view.add_item(info.ManageEventButton(event))

    if is_edit:
        msg = await interaction.response.edit_message(content=body, view=view)
    else:
        msg = await interaction.followup.send(content=body, ephemeral=True, view=view)
    view.message = msg

# --- Command Entrypoint ---

async def event_info(interaction: discord.Interaction, event_name: str = None):
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
