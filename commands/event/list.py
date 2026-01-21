from discord.ui import Button
from datetime import timedelta
from commands.user import timezone
from core import auth, events, utils, userdata, entitlements
from commands.event import register, responses, manage
import discord

# --- Event Rendering ---
def group_consecutive_hours_local(local_availability: list) -> list:
    """
    Accepts list of (date_string, [(local_dt, utc_str, rsvps_dict), ...])
    Groups by date, merges consecutive slots, and finds max RSVPs per range.
    """
    output = []

    for date_str, slots in local_availability:
        if not slots:
            continue

        # Sort slots by local datetime
        slots.sort(key=lambda x: x[0])

        merged_ranges = []
        current_start = slots[0][0]
        current_end = current_start + timedelta(hours=1)
        max_rsvps = len(slots[0][2])  # Initial RSVP count

        for i in range(1, len(slots)):
            local_dt, _, rsvps = slots[i]
            slot_end = local_dt + timedelta(hours=1)
            rsvp_count = len(rsvps)

            if local_dt <= current_end + timedelta(minutes=5):  # still mergeable
                current_end = max(current_end, slot_end)
                max_rsvps = max(max_rsvps, rsvp_count)
            else:
                # close current merged range
                merged_ranges.append(
                    f"\n        --`{current_start.strftime('%I%p').lower()} -> {current_end.strftime('%I%p').lower()}` (RSVPs: {max_rsvps})"
                )
                current_start = local_dt
                current_end = slot_end
                max_rsvps = rsvp_count

        # Final range
        merged_ranges.append(
            f"\n        --`{current_start.strftime('%I%p').lower()} -> {current_end.strftime('%I%p').lower()}` (RSVPs: {max_rsvps})"
        )

        output.append(f"{date_str} {''.join(merged_ranges)}")

    return output

async def format_single_event(interaction, event, is_edit=False, inherit_view=None):
    user_tz = userdata.get_user_timezone(interaction.user.id)
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
    local_availability = utils.from_utc_to_local(event.availability, user_tz)
    proposed_dates = "\n".join(f"• {d}" for d in group_consecutive_hours_local(local_availability))

    # Build premium badges/indicators
    badges = []
    if event.is_recurring:
        badges.append("🔄 Recurring")

    badge_line = f"✨ {' • '.join(badges)}\n" if badges else ""

    body = (
        f"📅 **Event:** `{event.event_name}`\n"
        f"{badge_line}"
        f"🙋 **Organizer:** <@{event.organizer}>\n"
        f"✅ **Confirmed Date:** *{event.confirmed_date or 'TBD'}*\n"
        f"🗓️ **Proposed Dates (Your Timezone - `{user_tz}`):**\n{proposed_dates or '*None yet*'}\n"
    )

    if inherit_view:
        view = inherit_view
    else:
        view = EventView(event, user_tz, is_selected=(str(interaction.user.id) in event.rsvp))

    if event.confirmed_date and event.confirmed_date != "TBD":
        view.add_item(NotificationButton(event))

    if await auth.authenticate(interaction.user, event.organizer):
        view.add_item(ManageEventButton(event, user_tz))

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
    def __init__(self, event, user_tz):
        self.event = event
        self.user_tz = user_tz
        self.event_name = event.event_name
        super().__init__(label="Info", style=discord.ButtonStyle.secondary, custom_id=f"info:{self.event_name}")

    async def callback(self, interaction: discord.Interaction):
        local_availability = utils.from_utc_to_local( self.event.availability, self.user_tz)
        view = responses.OverlapSummaryView(self.event, local_availability, self.user_tz, show_back_button=True)
        msg = await interaction.response.edit_message(
            content=f"📊 Top availability slots for **{self.event.event_name}**",
            view=view
        )
        view.message = msg  # Optional if you want expiry cleanup on info view

class NotificationButton(Button):
    def __init__(self, event):
        self.event = event
        self.event_name = event.event_name
        super().__init__(label="🔔 Remind Me", style=discord.ButtonStyle.secondary, custom_id=f"notifications:{self.event_name}")

    async def callback(self, interaction: discord.Interaction):
        from commands.user import notifications as notif_commands
        await notif_commands.show_notification_settings(interaction, self.event_name)

class ManageEventButton(Button):
    def __init__(self, event, user_tz):
        self.event = event
        self.user_tz = user_tz
        self.event_name = event.event_name
        super().__init__(label="Manage Event", style=discord.ButtonStyle.danger, custom_id=f"manage_event:{self.event_name}")

    async def callback(self, interaction: discord.Interaction):
        if not await auth.authenticate(interaction.user, self.event.organizer):
            await interaction.response.send_message("❌ You don’t have permission to manage this event.", ephemeral=True)
            return

        view = ManageEventView(self.event, self.user_tz, interaction.guild.id, interaction.user)
        await interaction.response.edit_message(
            view=view
        )
        view.message = interaction.message

# --- View Definitions ---

class EventView(utils.ExpiringView):
    def __init__(self, event, user_tz, is_selected=False):
        super().__init__(timeout=180)
        self.add_item(RegisterButton(event, is_selected))
        self.add_item(InfoButton(event, user_tz))

class ManageEventView(utils.ExpiringView):
    def __init__(self, event, user_tz,guild_id: int, user):
        super().__init__(timeout=180)
        self.event = event
        self.user_tz = user_tz
        self.event_details = event  # Added to fix missing field in delete
        self.guild_id = guild_id
        self.user = user

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel_button(self, interaction: discord.Interaction, _):
        if not await auth.authenticate(interaction.user, self.event.organizer):
            await interaction.response.send_message("❌ You don’t have permission to view this event.", ephemeral=True)
            return

        is_selected = str(interaction.user.id) in self.event.rsvp
        view = EventView(self.event, self.user_tz, is_selected=is_selected)

        if self.event.confirmed_date and self.event.confirmed_date != "TBD":
            view.add_item(NotificationButton(self.event))

        if await auth.authenticate(self.user, self.event.organizer):
            view.add_item(ManageEventButton(self.event, self.user_tz))

        await interaction.response.edit_message(view=view)
        view.message = interaction.message

    @discord.ui.button(label="Edit Event", style=discord.ButtonStyle.primary, disabled=True)
    async def edit_button(self, interaction: discord.Interaction, _):
        # TODO: Implement edit event flow
        await interaction.response.defer()

    @discord.ui.button(label="Confirm Date", style=discord.ButtonStyle.success, disabled=True)
    async def confirm_button(self, interaction: discord.Interaction, _):
        # TODO: Implement confirm datetime flow
        await interaction.response.defer()

    @discord.ui.button(label="Delete", style=discord.ButtonStyle.danger)
    async def delete_button(self, interaction: discord.Interaction, _):
        if not await auth.authenticate(interaction.user, self.event.organizer):
            await interaction.response.send_message("❌ You don't have permission to delete this event.", ephemeral=True)
            return

        await manage._prompt_event_deletion(
            interaction,
            self.guild_id,
            self.event.event_name,
            self.event_details
        )
