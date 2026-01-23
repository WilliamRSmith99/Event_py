from discord.ui import Button
from datetime import datetime, timedelta
from commands.user import timezone
from core import auth, events, utils, userdata, entitlements, notifications, conf
from commands.event import register, responses, manage
import discord

# --- Event Rendering ---
def group_consecutive_hours_local(local_availability: list, use_24hr: bool = False) -> list:
    """
    Accepts list of (date_string, [(local_dt, utc_str, rsvps_dict), ...])
    Groups by date, merges consecutive slots, and finds max RSVPs per range.

    Args:
        local_availability: List of availability data
        use_24hr: If True, use 24-hour time format
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
                time_range = utils.format_time_range(current_start, current_end, use_24hr)
                merged_ranges.append(
                    f"\n        --`{time_range}` (RSVPs: {max_rsvps})"
                )
                current_start = local_dt
                current_end = slot_end
                max_rsvps = rsvp_count

        # Final range
        time_range = utils.format_time_range(current_start, current_end, use_24hr)
        merged_ranges.append(
            f"\n        --`{time_range}` (RSVPs: {max_rsvps})"
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

    # Get server time format preference
    server_config = conf.get_config(interaction.guild_id)
    use_24hr = getattr(server_config, "use_24hr_time", False)

    local_availability = utils.from_utc_to_local(event.availability, user_tz)
    proposed_dates = "\n".join(f"• {d}" for d in group_consecutive_hours_local(local_availability, use_24hr))

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
    # Use get_active_events to exclude archived/past events
    events_found = events.get_active_events(interaction.guild_id, event_name)

    if not events_found:
        # Check if there are archived events to mention
        archived = events.get_archived_events(interaction.guild_id)
        if event_name:
            message = f"❌ No active events found for `{event_name}`."
            if event_name.lower() in [e.lower() for e in archived.keys()]:
                message += "\n\n*This event has ended.*"
        else:
            message = "📅 No upcoming events.\n\n\n 🤫 *psst*: create new events with `/newevent`"
            if archived:
                message += f"\n\n*({len(archived)} past events in history)*"

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

    @discord.ui.button(label="Confirm Date", style=discord.ButtonStyle.success)
    async def confirm_button(self, interaction: discord.Interaction, _):
        if not await auth.authenticate(interaction.user, self.event.organizer):
            await interaction.response.send_message("❌ You don't have permission to confirm this event.", ephemeral=True)
            return

        # Show date/time selection for confirmation
        local_availability = utils.from_utc_to_local(self.event.availability, self.user_tz)
        if not local_availability:
            await interaction.response.send_message("❌ No availability has been collected yet.", ephemeral=True)
            return

        view = ConfirmDateView(self.event, local_availability, self.user_tz, self.guild_id, self.user)
        await interaction.response.edit_message(
            content=f"📅 **Select confirmed date/time for {self.event.event_name}:**",
            view=view
        )
        view.message = interaction.message

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


class ConfirmDateSlotButton(Button):
    """Button for selecting a specific time slot to confirm."""
    def __init__(self, label: str, utc_iso: str, attendee_count: int, row: int):
        display_label = f"{label} ({attendee_count})"
        super().__init__(
            label=display_label,
            style=discord.ButtonStyle.primary,
            custom_id=f"confirm_slot_{utc_iso}",
            row=row
        )
        self.utc_iso = utc_iso
        self.attendee_count = attendee_count

    async def callback(self, interaction: discord.Interaction):
        view: ConfirmDateView = self.view
        view.selected_slot = self.utc_iso
        view.update_buttons()
        await interaction.response.edit_message(view=view)


class ConfirmDateView(utils.ExpiringView):
    """View for selecting and confirming the event date/time."""
    MAX_SLOTS_PER_PAGE = 15

    def __init__(self, event, local_availability, user_tz: str, guild_id: int, user, page: int = 0):
        super().__init__(timeout=180)
        self.event = event
        self.local_availability = local_availability
        self.user_tz = user_tz
        self.guild_id = guild_id
        self.user = user
        self.page = page
        self.selected_slot = None

        # Get server time format preference
        server_config = conf.get_config(guild_id)
        self.use_24hr = getattr(server_config, "use_24hr_time", False)

        # Flatten all slots with their info
        self.all_slots = []
        for date_label, slots in local_availability:
            for local_dt, utc_iso, signup_map in slots:
                time_str = utils.format_time(local_dt, self.use_24hr, include_date=True)
                self.all_slots.append((time_str, utc_iso, len(signup_map)))

        # Sort by attendee count (descending)
        self.all_slots.sort(key=lambda x: x[2], reverse=True)

        self.total_pages = max(1, (len(self.all_slots) - 1) // self.MAX_SLOTS_PER_PAGE + 1)
        self.update_buttons()

    def update_buttons(self):
        self.clear_items()

        start = self.page * self.MAX_SLOTS_PER_PAGE
        end = start + self.MAX_SLOTS_PER_PAGE
        page_slots = self.all_slots[start:end]

        # Add slot buttons (3 rows of 5)
        for i, (label, utc_iso, count) in enumerate(page_slots):
            row = i // 5
            btn = ConfirmDateSlotButton(label, utc_iso, count, row)
            if utc_iso == self.selected_slot:
                btn.style = discord.ButtonStyle.success
            self.add_item(btn)

        # Navigation row (row 3)
        nav_row = 3

        # Previous page
        prev_btn = Button(label="⬅️ Previous", style=discord.ButtonStyle.secondary, row=nav_row)
        prev_btn.disabled = self.page == 0
        prev_btn.callback = self._prev_page
        self.add_item(prev_btn)

        # Confirm selection
        confirm_btn = Button(label="✅ Confirm Selection", style=discord.ButtonStyle.success, row=nav_row)
        confirm_btn.disabled = self.selected_slot is None
        confirm_btn.callback = self._confirm_selection
        self.add_item(confirm_btn)

        # Cancel
        cancel_btn = Button(label="Cancel", style=discord.ButtonStyle.danger, row=nav_row)
        cancel_btn.callback = self._cancel
        self.add_item(cancel_btn)

        # Next page
        next_btn = Button(label="Next ➡️", style=discord.ButtonStyle.secondary, row=nav_row)
        next_btn.disabled = self.page >= self.total_pages - 1
        next_btn.callback = self._next_page
        self.add_item(next_btn)

    async def _prev_page(self, interaction: discord.Interaction):
        self.page = max(0, self.page - 1)
        self.update_buttons()
        await interaction.response.edit_message(view=self)

    async def _next_page(self, interaction: discord.Interaction):
        self.page = min(self.total_pages - 1, self.page + 1)
        self.update_buttons()
        await interaction.response.edit_message(view=self)

    async def _cancel(self, interaction: discord.Interaction):
        is_selected = str(interaction.user.id) in self.event.rsvp
        view = EventView(self.event, self.user_tz, is_selected=is_selected)

        if self.event.confirmed_date and self.event.confirmed_date != "TBD":
            view.add_item(NotificationButton(self.event))

        if await auth.authenticate(self.user, self.event.organizer):
            view.add_item(ManageEventButton(self.event, self.user_tz))

        local_availability = utils.from_utc_to_local(self.event.availability, self.user_tz)
        proposed_dates = "\n".join(f"• {d}" for d in group_consecutive_hours_local(local_availability, self.use_24hr))

        badges = []
        if self.event.is_recurring:
            badges.append("🔄 Recurring")
        badge_line = f"✨ {' • '.join(badges)}\n" if badges else ""

        body = (
            f"📅 **Event:** `{self.event.event_name}`\n"
            f"{badge_line}"
            f"🙋 **Organizer:** <@{self.event.organizer}>\n"
            f"✅ **Confirmed Date:** *{self.event.confirmed_date or 'TBD'}*\n"
            f"🗓️ **Proposed Dates (Your Timezone - `{self.user_tz}`):**\n{proposed_dates or '*None yet*'}\n"
        )

        await interaction.response.edit_message(content=body, view=view)
        view.message = interaction.message

    async def _confirm_selection(self, interaction: discord.Interaction):
        if not self.selected_slot:
            await interaction.response.send_message("❌ Please select a time slot first.", ephemeral=True)
            return

        if not await auth.authenticate(interaction.user, self.event.organizer):
            await interaction.response.send_message("❌ You don't have permission to confirm this event.", ephemeral=True)
            return

        # Find the selected slot's display label
        selected_label = None
        for label, utc_iso, _ in self.all_slots:
            if utc_iso == self.selected_slot:
                selected_label = label
                break

        # Update the event's confirmed_date
        self.event.confirmed_date = self.selected_slot
        events.modify_event(self.event)

        # Update the bulletin if one exists
        try:
            from core import bulletins
            await bulletins.update_bulletin_header(interaction.client, self.event)
        except Exception as e:
            # Don't fail the confirmation if bulletin update fails
            pass

        # Send confirmation notifications to users who have notification preferences
        try:
            confirmed_time = datetime.fromisoformat(self.selected_slot)
            await notifications.notify_event_confirmed(
                interaction.client,
                self.guild_id,
                self.event.event_name,
                confirmed_time
            )
        except Exception as e:
            # Don't fail the confirmation if notifications fail
            pass

        # Return to event view
        is_selected = str(interaction.user.id) in self.event.rsvp
        view = EventView(self.event, self.user_tz, is_selected=is_selected)
        view.add_item(NotificationButton(self.event))

        if await auth.authenticate(self.user, self.event.organizer):
            view.add_item(ManageEventButton(self.event, self.user_tz))

        local_availability = utils.from_utc_to_local(self.event.availability, self.user_tz)
        proposed_dates = "\n".join(f"• {d}" for d in group_consecutive_hours_local(local_availability, self.use_24hr))

        badges = []
        if self.event.is_recurring:
            badges.append("🔄 Recurring")
        badge_line = f"✨ {' • '.join(badges)}\n" if badges else ""

        body = (
            f"📅 **Event:** `{self.event.event_name}`\n"
            f"{badge_line}"
            f"🙋 **Organizer:** <@{self.event.organizer}>\n"
            f"✅ **Confirmed Date:** *{selected_label}*\n"
            f"🗓️ **Proposed Dates (Your Timezone - `{self.user_tz}`):**\n{proposed_dates or '*None yet*'}\n"
        )

        await interaction.response.edit_message(
            content=f"✅ **Event confirmed for {selected_label}!**\n\n{body}",
            view=view
        )
        view.message = interaction.message
