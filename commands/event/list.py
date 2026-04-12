from discord.ui import Button
from datetime import datetime, timedelta
from commands.user import timezone
from core import auth, events, utils, userdata, entitlements, notifications, conf
from core.logging import get_logger
from commands.event import register, responses, manage
import discord

logger = get_logger(__name__)

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

    # Get user's effective time format preference (user pref > server default)
    use_24hr = userdata.get_effective_time_format(interaction.user.id, interaction.guild_id)

    local_availability = utils.from_utc_to_local(event.availability, user_tz)
    proposed_dates = "\n".join(f"• {d}" for d in group_consecutive_hours_local(local_availability, use_24hr))

    # Build premium badges/indicators
    badges = []
    if event.is_recurring:
        badges.append("🔄 Recurring")

    badge_line = f"✨ {' • '.join(badges)}\n" if badges else ""

    # Format confirmed date as Discord timestamp if set
    if event.confirmed_date and event.confirmed_date != "TBD":
        try:
            confirmed_dt = datetime.fromisoformat(event.confirmed_date)
            confirmed_display = utils.to_discord_timestamp(confirmed_dt, 'F')
        except ValueError:
            confirmed_display = event.confirmed_date
    else:
        confirmed_display = "TBD"

    # Only show proposed dates if event is not yet confirmed
    if event.confirmed_date and event.confirmed_date != "TBD":
        # Count attendees for the confirmed slot
        confirmed_slot_data = event.availability.get(event.confirmed_date, {})
        attendee_count = len(confirmed_slot_data)
        max_display = f"/{event.max_attendees}" if event.max_attendees else ""

        # Calculate waitlist if max_attendees is set
        waitlist_line = ""
        if event.max_attendees:
            max_int = int(event.max_attendees)
            waitlist_count = sum(1 for pos in confirmed_slot_data.keys() if int(pos) > max_int)
            if waitlist_count > 0:
                waitlist_line = f"⏳ **Waitlist:** {waitlist_count}\n"

        body = (
            f"📅 **Event:** `{event.event_name}`\n"
            f"{badge_line}"
            f"🙋 **Organizer:** <@{event.organizer}>\n"
            f"✅ **Confirmed Date:** {confirmed_display}\n"
            f"👥 **Registered:** {attendee_count}{max_display}\n"
            f"{waitlist_line}"
        )
    else:
        body = (
            f"📅 **Event:** `{event.event_name}`\n"
            f"{badge_line}"
            f"🙋 **Organizer:** <@{event.organizer}>\n"
            f"✅ **Confirmed Date:** *{confirmed_display}*\n"
            f"🗓️ **Proposed Dates (Your Timezone - `{user_tz}`):**\n{proposed_dates or '*None yet*'}\n"
        )

    if inherit_view:
        view = inherit_view
    else:
        view = EventView(event, user_tz, is_selected=(interaction.user.id in event.rsvp))

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
    try:
        await interaction.response.defer(ephemeral=True, thinking=True)
    except discord.InteractionResponded:
        # Already responded, which is unusual here, but we can proceed with followup
        pass
    except Exception as e:
        logger.error(f"Error deferring interaction in event_info: {e}", exc_info=e)
        # If we can't even defer, we probably can't send a message either, but try once.
        try:
            await interaction.followup.send(
                "❌ An error occurred while loading events. Please try again.",
                ephemeral=True
            )
        except Exception:
            logger.warning("Could not send error response to interaction after defer failure")
        return

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
            message = "📅 No upcoming events.\n\n\n 🤫 *psst*: create new events with `/create`"
            if archived:
                message += f"\n\n*({len(archived)} past events in history)*"

        await interaction.followup.send(message, ephemeral=True)
        return

    # Send events using followup
    for event in events_found.values():
        try:
            await format_single_event(interaction, event, is_edit=False)
        except Exception as e:
            logger.error(f"Error formatting event {event.event_name}: {e}", exc_info=e)
            continue

# --- Custom Button Implementations ---

class RegisterButton(Button):
    def __init__(self, event, is_selected: bool):
        self.event = event
        self.event_name = event.event_name
        button_label = "Edit Registration" if is_selected else "Register"
        button_style = discord.ButtonStyle.danger if is_selected else discord.ButtonStyle.primary
        # Use unique prefix to avoid conflict with global bulletin handler
        super().__init__(label=button_label, style=button_style)

    async def callback(self, interaction: discord.Interaction):
        await register.schedule_command(interaction, self.event_name)

class ViewAttendeesButton(Button):
    def __init__(self, event, user_tz):
        self.event = event
        self.user_tz = user_tz
        self.event_name = event.event_name
        super().__init__(label="View Attendees", style=discord.ButtonStyle.secondary, custom_id=f"info:{self.event_name}")

    async def callback(self, interaction: discord.Interaction):
        local_availability = utils.from_utc_to_local( self.event.availability, self.user_tz)
        use_24hr = userdata.get_effective_time_format(interaction.user.id, interaction.guild_id)
        view = responses.OverlapSummaryView(self.event, local_availability, self.user_tz, show_back_button=True, use_24hr=use_24hr)
        msg = await interaction.response.edit_message(
            content=view.get_content(),
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
        self.add_item(ViewAttendeesButton(event, user_tz))

class ManageEventView(utils.ExpiringView):
    def __init__(self, event, user_tz, guild_id: int, user):
        super().__init__(timeout=180)
        self.event = event
        self.user_tz = user_tz
        self.event_details = event  # Added to fix missing field in delete
        self.guild_id = guild_id
        self.user = user
        self._setup_buttons()

    def _setup_buttons(self):
        # Cancel button
        cancel_btn = Button(label="Cancel", style=discord.ButtonStyle.secondary)
        cancel_btn.callback = self._cancel_callback
        self.add_item(cancel_btn)

        # Edit Event button (now enabled)
        edit_btn = Button(label="Edit Event", style=discord.ButtonStyle.primary)
        edit_btn.callback = self._edit_callback
        self.add_item(edit_btn)

        # Confirm/Change Time button - label depends on whether event is already confirmed
        is_confirmed = self.event.confirmed_date and self.event.confirmed_date != "TBD"
        confirm_label = "Change Time" if is_confirmed else "Confirm Date"
        confirm_btn = Button(label=confirm_label, style=discord.ButtonStyle.success)
        confirm_btn.callback = self._confirm_callback
        self.add_item(confirm_btn)

        # Delete button
        delete_btn = Button(label="Delete", style=discord.ButtonStyle.danger)
        delete_btn.callback = self._delete_callback
        self.add_item(delete_btn)

    async def _cancel_callback(self, interaction: discord.Interaction):
        if not await auth.authenticate(interaction.user, self.event.organizer):
            await interaction.response.send_message("❌ You don't have permission to view this event.", ephemeral=True)
            return

        is_selected = interaction.user.id in self.event.rsvp
        view = EventView(self.event, self.user_tz, is_selected=is_selected)

        if self.event.confirmed_date and self.event.confirmed_date != "TBD":
            view.add_item(NotificationButton(self.event))

        if await auth.authenticate(self.user, self.event.organizer):
            view.add_item(ManageEventButton(self.event, self.user_tz))

        await interaction.response.edit_message(view=view)
        view.message = interaction.message

    async def _edit_callback(self, interaction: discord.Interaction):
        if not await auth.authenticate(interaction.user, self.event.organizer):
            await interaction.response.send_message("❌ You don't have permission to edit this event.", ephemeral=True)
            return

        # Show edit event options
        view = EditEventView(self.event, self.user_tz, self.guild_id, self.user)
        await interaction.response.edit_message(
            content=f"✏️ **Edit {self.event.event_name}:**\nSelect what you want to edit:",
            view=view
        )
        view.message = interaction.message

    async def _confirm_callback(self, interaction: discord.Interaction):
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

    async def _delete_callback(self, interaction: discord.Interaction):
        if not await auth.authenticate(interaction.user, self.event.organizer):
            await interaction.response.send_message("❌ You don't have permission to delete this event.", ephemeral=True)
            return

        await manage._prompt_event_deletion(
            interaction,
            self.guild_id,
            self.event.event_name,
            self.event_details
        )


class EditEventView(utils.ExpiringView):
    """View for editing event properties."""
    def __init__(self, event, user_tz, guild_id: int, user):
        super().__init__(timeout=180)
        self.event = event
        self.user_tz = user_tz
        self.guild_id = guild_id
        self.user = user
        self._setup_buttons()

    def _setup_buttons(self):
        # Edit Name button
        name_btn = Button(label="Edit Name", style=discord.ButtonStyle.primary)
        name_btn.callback = self._edit_name_callback
        self.add_item(name_btn)

        # Edit Max Attendees button
        attendees_btn = Button(label="Edit Max Attendees", style=discord.ButtonStyle.primary)
        attendees_btn.callback = self._edit_attendees_callback
        self.add_item(attendees_btn)

        # Add Time Slots button
        slots_btn = Button(label="Add Time Slots", style=discord.ButtonStyle.primary)
        slots_btn.callback = self._add_slots_callback
        self.add_item(slots_btn)

        # Back button
        back_btn = Button(label="Back", style=discord.ButtonStyle.secondary)
        back_btn.callback = self._back_callback
        self.add_item(back_btn)

    async def _edit_name_callback(self, interaction: discord.Interaction):
        modal = EditEventNameModal(self.event, self.user_tz, self.guild_id, self.user)
        await interaction.response.send_modal(modal)

    async def _edit_attendees_callback(self, interaction: discord.Interaction):
        modal = EditEventAttendeesModal(self.event, self.user_tz, self.guild_id, self.user)
        await interaction.response.send_modal(modal)

    async def _add_slots_callback(self, interaction: discord.Interaction):
        from commands.event.create import GenerateProposedDates
        # Seed a fresh event-shell with the date picker's 14-day window.
        # The selected ISO slots will be merged into self.event on completion.
        shell = events.EventState(
            guild_id=self.event.guild_id,
            event_name=self.event.event_name,
            max_attendees=self.event.max_attendees,
            organizer=self.event.organizer,
            organizer_cname=self.event.organizer_cname,
            confirmed_date=self.event.confirmed_date,
            slots=GenerateProposedDates(),
            availability={},
        )
        view = AddSlotsDateView(shell, self.event, self.user_tz, self.guild_id, self.user)
        await interaction.response.edit_message(
            content=f"📅 **Select new dates to add slots to {self.event.event_name}:**",
            view=view,
        )

    async def _back_callback(self, interaction: discord.Interaction):
        view = ManageEventView(self.event, self.user_tz, self.guild_id, self.user)
        # Rebuild the event body
        local_availability = utils.from_utc_to_local(self.event.availability, self.user_tz)
        use_24hr = userdata.get_effective_time_format(self.user.id, self.guild_id)
        proposed_dates = "\n".join(f"• {d}" for d in group_consecutive_hours_local(local_availability, use_24hr))

        badges = []
        if self.event.is_recurring:
            badges.append("🔄 Recurring")
        badge_line = f"✨ {' • '.join(badges)}\n" if badges else ""

        # Format confirmed date
        if self.event.confirmed_date and self.event.confirmed_date != "TBD":
            try:
                confirmed_dt = datetime.fromisoformat(self.event.confirmed_date)
                confirmed_display = utils.to_discord_timestamp(confirmed_dt, 'F')
            except ValueError:
                confirmed_display = self.event.confirmed_date
            # Count attendees for the confirmed slot
            confirmed_slot_data = self.event.availability.get(self.event.confirmed_date, {})
            attendee_count = len(confirmed_slot_data)
            max_display = f"/{self.event.max_attendees}" if self.event.max_attendees else ""

            # Calculate waitlist if max_attendees is set
            waitlist_line = ""
            if self.event.max_attendees:
                max_int = int(self.event.max_attendees)
                waitlist_count = sum(1 for pos in confirmed_slot_data.keys() if int(pos) > max_int)
                if waitlist_count > 0:
                    waitlist_line = f"⏳ **Waitlist:** {waitlist_count}\n"

            body = (
                f"📅 **Event:** `{self.event.event_name}`\n"
                f"{badge_line}"
                f"🙋 **Organizer:** <@{self.event.organizer}>\n"
                f"✅ **Confirmed Date:** {confirmed_display}\n"
                f"👥 **Registered:** {attendee_count}{max_display}\n"
                f"{waitlist_line}"
            )
        else:
            body = (
                f"📅 **Event:** `{self.event.event_name}`\n"
                f"{badge_line}"
                f"🙋 **Organizer:** <@{self.event.organizer}>\n"
                f"✅ **Confirmed Date:** *TBD*\n"
                f"🗓️ **Proposed Dates (Your Timezone - `{self.user_tz}`):**\n{proposed_dates or '*None yet*'}\n"
            )

        await interaction.response.edit_message(content=body, view=view)
        view.message = interaction.message


class EditEventNameModal(discord.ui.Modal, title="Edit Event Name"):
    new_name = discord.ui.TextInput(label="New Event Name", placeholder="Enter new event name")

    def __init__(self, event, user_tz, guild_id, user):
        super().__init__()
        self.event = event
        self.user_tz = user_tz
        self.guild_id = guild_id
        self.user = user
        self.new_name.default = event.event_name

    async def on_submit(self, interaction: discord.Interaction):
        old_name = self.event.event_name
        new_name = self.new_name.value.strip()

        if not new_name:
            await interaction.response.send_message("❌ Event name cannot be empty.", ephemeral=True)
            return

        # Migrate notification preferences before renaming
        from core import notifications
        migrated_count = notifications.migrate_event_notification_preferences(
            self.guild_id,
            old_name,
            new_name
        )

        # Use the new atomic rename function
        renamed_event = events.rename_event(self.guild_id, old_name, new_name)

        if not renamed_event:
            # The rename function logs the specific error
            await interaction.response.send_message(
                f"❌ Failed to rename event. The name `{new_name}` might already exist.",
                ephemeral=True
            )
            # Rollback notification migration if needed (or handle more gracefully)
            notifications.migrate_event_notification_preferences(self.guild_id, new_name, old_name)
            return

        # Update bulletin if exists
        try:
            from core import bulletins
            await bulletins.update_bulletin_header(interaction.client, renamed_event)
        except Exception as e:
            logger.error(f"Failed to update bulletin after rename: {e}", exc_info=e)
            pass

        message = f"✅ Event renamed from `{old_name}` to `{new_name}`."
        if migrated_count > 0:
            message += f"\n\n📢 Migrated {migrated_count} notification preference(s)."
        
        await interaction.response.send_message(message, ephemeral=True)


class EditEventAttendeesModal(discord.ui.Modal, title="Edit Max Attendees"):
    max_attendees = discord.ui.TextInput(
        label="Max Attendees",
        placeholder="Enter a number or leave empty for unlimited"
    )

    def __init__(self, event, user_tz, guild_id, user):
        super().__init__()
        self.event = event
        self.user_tz = user_tz
        self.guild_id = guild_id
        self.user = user
        self.max_attendees.default = str(event.max_attendees) if event.max_attendees else ""

    async def on_submit(self, interaction: discord.Interaction):
        value = self.max_attendees.value.strip()

        if value:
            try:
                max_val = int(value)
                if max_val < 1:
                    await interaction.response.send_message("❌ Max attendees must be at least 1.", ephemeral=True)
                    return
                self.event.max_attendees = str(max_val)
            except ValueError:
                await interaction.response.send_message("❌ Please enter a valid number.", ephemeral=True)
                return
        else:
            self.event.max_attendees = None

        events.modify_event(self.event)

        # Update bulletin if exists
        try:
            from core import bulletins
            await bulletins.update_bulletin_header(interaction.client, self.event)
        except Exception as e:
            logger.warning(f"Failed to update bulletin after attendee edit: {e}")

        display = self.event.max_attendees or "unlimited"
        await interaction.response.send_message(
            f"✅ Max attendees updated to {display}.",
            ephemeral=True
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

        # Get user's effective time format preference
        self.use_24hr = userdata.get_effective_time_format(user.id, guild_id)

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
        is_selected = interaction.user.id in self.event.rsvp
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

        # Format confirmed date as Discord timestamp if set
        if self.event.confirmed_date and self.event.confirmed_date != "TBD":
            try:
                confirmed_dt = datetime.fromisoformat(self.event.confirmed_date)
                confirmed_display = utils.to_discord_timestamp(confirmed_dt, 'F')
            except ValueError:
                confirmed_display = self.event.confirmed_date
            # Count attendees for the confirmed slot
            confirmed_slot_data = self.event.availability.get(self.event.confirmed_date, {})
            attendee_count = len(confirmed_slot_data)
            max_display = f"/{self.event.max_attendees}" if self.event.max_attendees else ""

            # Calculate waitlist if max_attendees is set
            waitlist_line = ""
            if self.event.max_attendees:
                max_int = int(self.event.max_attendees)
                waitlist_count = sum(1 for pos in confirmed_slot_data.keys() if int(pos) > max_int)
                if waitlist_count > 0:
                    waitlist_line = f"⏳ **Waitlist:** {waitlist_count}\n"

            body = (
                f"📅 **Event:** `{self.event.event_name}`\n"
                f"{badge_line}"
                f"🙋 **Organizer:** <@{self.event.organizer}>\n"
                f"✅ **Confirmed Date:** {confirmed_display}\n"
                f"👥 **Registered:** {attendee_count}{max_display}\n"
                f"{waitlist_line}"
            )
        else:
            body = (
                f"📅 **Event:** `{self.event.event_name}`\n"
                f"{badge_line}"
                f"🙋 **Organizer:** <@{self.event.organizer}>\n"
                f"✅ **Confirmed Date:** *TBD*\n"
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
            logger.warning(f"Failed to update bulletin after event confirmation: {e}")

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
            logger.warning(f"Failed to send confirmation notifications: {e}")

        # Return to event view
        is_selected = interaction.user.id in self.event.rsvp
        view = EventView(self.event, self.user_tz, is_selected=is_selected)
        view.add_item(NotificationButton(self.event))

        if await auth.authenticate(self.user, self.event.organizer):
            view.add_item(ManageEventButton(self.event, self.user_tz))

        badges = []
        if self.event.is_recurring:
            badges.append("🔄 Recurring")
        badge_line = f"✨ {' • '.join(badges)}\n" if badges else ""

        # Format confirmed date as Discord timestamp
        confirmed_dt = datetime.fromisoformat(self.selected_slot)
        confirmed_display = utils.to_discord_timestamp(confirmed_dt, 'F')

        # Count attendees for the newly confirmed slot
        confirmed_slot_data = self.event.availability.get(self.selected_slot, {})
        attendee_count = len(confirmed_slot_data)
        max_display = f"/{self.event.max_attendees}" if self.event.max_attendees else ""

        # Calculate waitlist if max_attendees is set
        waitlist_line = ""
        if self.event.max_attendees:
            max_int = int(self.event.max_attendees)
            waitlist_count = sum(1 for pos in confirmed_slot_data.keys() if int(pos) > max_int)
            if waitlist_count > 0:
                waitlist_line = f"⏳ **Waitlist:** {waitlist_count}\n"

        body = (
            f"📅 **Event:** `{self.event.event_name}`\n"
            f"{badge_line}"
            f"🙋 **Organizer:** <@{self.event.organizer}>\n"
            f"✅ **Confirmed Date:** {confirmed_display}\n"
            f"👥 **Registered:** {attendee_count}{max_display}\n"
            f"{waitlist_line}"
        )

        await interaction.response.edit_message(
            content=f"✅ **Event confirmed for {confirmed_display}!**\n\n{body}",
            view=view
        )
        view.message = interaction.message


# =============================================================================
# Add Slots Flow  (Edit dates / Add time slots)
# =============================================================================

class AddSlotsDateView(utils.ExpiringView):
    """Date picker for adding new time slots to an existing event."""

    def __init__(self, shell, real_event, user_tz: str, guild_id: int, user):
        super().__init__(timeout=300)
        self.shell = shell          # temporary EventState with date picker's slots
        self.real_event = real_event  # actual event being edited
        self.user_tz = user_tz
        self.guild_id = guild_id
        self.user = user
        # Pre-highlight dates that already have slots in the real event
        import pytz
        from datetime import datetime as _pdt
        tz = pytz.timezone(user_tz)
        existing_dates: set = set()
        for iso in real_event.availability:
            try:
                dt = _pdt.fromisoformat(iso).replace(tzinfo=pytz.utc).astimezone(tz)
                existing_dates.add(dt.strftime("%A, %m/%d/%y"))
            except ValueError:
                pass
        self.selected_dates: set = existing_dates & set(shell.slots)
        self._render()

    def _render(self):
        from datetime import datetime as _dt
        self.clear_items()
        today = _dt.utcnow().date()

        layout = [self.shell.slots[i:i+5] for i in range(0, len(self.shell.slots), 5)]
        for row_items in layout:
            for date_str in row_items:
                date_obj = _dt.strptime(date_str, "%A, %m/%d/%y").date()
                is_selected = date_str in self.selected_dates
                style = discord.ButtonStyle.success if is_selected else discord.ButtonStyle.secondary
                btn = Button(label=date_str, style=style)
                btn.disabled = date_obj < today
                btn.callback = self._make_toggle(date_str)
                self.add_item(btn)

        submit = Button(label="✔ Select Times", style=discord.ButtonStyle.primary)
        submit.disabled = not self.selected_dates
        submit.callback = self._submit
        self.add_item(submit)

        cancel = Button(label="Cancel", style=discord.ButtonStyle.danger)
        cancel.callback = self._cancel
        self.add_item(cancel)

    def _make_toggle(self, date_str: str):
        async def toggle(interaction: discord.Interaction):
            if date_str in self.selected_dates:
                self.selected_dates.remove(date_str)
            else:
                self.selected_dates.add(date_str)
            self._render()
            await interaction.response.edit_message(view=self)
        return toggle

    async def _submit(self, interaction: discord.Interaction):
        from datetime import datetime as _dt
        sorted_dates = sorted(
            self.selected_dates,
            key=lambda d: _dt.strptime(d, "%A, %m/%d/%y"),
        )
        view = AddSlotsTimeView(
            dates=sorted_dates,
            real_event=self.real_event,
            user_tz=self.user_tz,
            guild_id=self.guild_id,
            user=self.user,
        )
        first = sorted_dates[0]
        await interaction.response.edit_message(
            content=f"🕐 **Select times to add for {self.real_event.event_name} on {first}:**",
            view=view,
        )

    async def _cancel(self, interaction: discord.Interaction):
        view = ManageEventView(self.real_event, self.user_tz, self.guild_id, self.user)
        await interaction.response.edit_message(content="", view=view)


class AddSlotsTimeView(utils.ExpiringView):
    """Time picker for one date when adding slots to an existing event."""

    def __init__(self, dates: list, real_event, user_tz: str, guild_id: int, user, date_index: int = 0, current_page: int = 0):
        super().__init__(timeout=300)
        self.dates = dates
        self.real_event = real_event
        self.user_tz = user_tz
        self.guild_id = guild_id
        self.user = user
        self.date_index = date_index
        self.current_page = current_page  # 0=AM, 1=PM

        # Pre-highlight times already scheduled for this date
        import pytz
        from datetime import datetime as _pdt
        tz = pytz.timezone(user_tz)
        date_str = dates[date_index]
        preselected: set = set()
        for iso in real_event.availability:
            try:
                dt = _pdt.fromisoformat(iso).replace(tzinfo=pytz.utc).astimezone(tz)
                if dt.strftime("%A, %m/%d/%y") == date_str:
                    period = "AM" if dt.hour < 12 else "PM"
                    preselected.add(f"{dt.hour % 12 or 12}:00 {period}")
            except ValueError:
                pass
        self.selected_times: set = preselected
        self._render()

    def _render(self):
        self.clear_items()

        hours = range(0, 12) if self.current_page == 0 else range(12, 24)
        period = "AM" if self.current_page == 0 else "PM"

        for i, h in enumerate(hours):
            label = f"{h % 12 or 12}:00 {period}"
            style = discord.ButtonStyle.success if label in self.selected_times else discord.ButtonStyle.secondary
            btn = Button(label=label, style=style, row=i // 4)
            btn.callback = self._make_toggle(label)
            self.add_item(btn)

        earlier = Button(label="◀ AM", style=discord.ButtonStyle.primary, row=3, disabled=self.current_page == 0)
        earlier.callback = self._earlier
        self.add_item(earlier)

        later = Button(label="PM ▶", style=discord.ButtonStyle.primary, row=3, disabled=self.current_page == 1)
        later.callback = self._later
        self.add_item(later)

        date_label = self.dates[self.date_index]
        is_last = self.date_index >= len(self.dates) - 1
        submit_label = "✔ Finish & Save" if is_last else f"✔ Next: {self.dates[self.date_index + 1]}"
        submit = Button(label=submit_label, style=discord.ButtonStyle.success, row=4)
        submit.disabled = not self.selected_times
        submit.callback = self._submit
        self.add_item(submit)

        cancel = Button(label="Cancel", style=discord.ButtonStyle.danger, row=4)
        cancel.callback = self._cancel
        self.add_item(cancel)

    def _make_toggle(self, label: str):
        async def toggle(interaction: discord.Interaction):
            if label in self.selected_times:
                self.selected_times.remove(label)
            else:
                self.selected_times.add(label)
            self._render()
            await interaction.response.edit_message(view=self)
        return toggle

    async def _earlier(self, interaction: discord.Interaction):
        self.current_page = 0
        self._render()
        await interaction.response.edit_message(view=self)

    async def _later(self, interaction: discord.Interaction):
        self.current_page = 1
        self._render()
        await interaction.response.edit_message(view=self)

    async def _submit(self, interaction: discord.Interaction):
        from core import utils as core_utils, userdata as ud
        from datetime import datetime as _dt

        date_str = self.dates[self.date_index]
        user_tz = self.user_tz

        for time_label in self.selected_times:
            try:
                datetime_str = f"{date_str} at {time_label}"
                utc_iso = core_utils.to_utc_isoformat(datetime_str, user_tz)
                self.real_event.availability[utc_iso] = self.real_event.availability.get(utc_iso, {})
            except Exception as e:
                logger.warning(f"Failed to parse datetime {date_str} {time_label}: {e}")

        events.modify_event(self.real_event)

        is_last = self.date_index >= len(self.dates) - 1
        if is_last:
            try:
                from core import bulletins
                if self.real_event.bulletin_thread_id:
                    await bulletins.refresh_bulletin_thread(interaction.client, self.real_event)
                else:
                    await bulletins.update_bulletin_header(interaction.client, self.real_event)
            except Exception as e:
                logger.warning(f"Failed to update bulletin after adding slots: {e}")

            view = ManageEventView(self.real_event, self.user_tz, self.guild_id, self.user)
            use_24hr = ud.get_effective_time_format(self.user.id, self.guild_id)
            local_avail = core_utils.from_utc_to_local(self.real_event.availability, self.user_tz)
            proposed_dates = "\n".join(f"• {d}" for d in group_consecutive_hours_local(local_avail, use_24hr))
            body = (
                f"📅 **Event:** `{self.real_event.event_name}`\n"
                f"🙋 **Organizer:** <@{self.real_event.organizer}>\n"
                f"✅ **Confirmed Date:** *{self.real_event.confirmed_date or 'TBD'}*\n"
                f"🗓️ **Proposed Dates (`{self.user_tz}`):**\n{proposed_dates or '*None yet*'}\n"
            )
            await interaction.response.edit_message(
                content=f"✅ **Slots added to {self.real_event.event_name}!**\n\n{body}",
                view=view,
            )
        else:
            next_date = self.dates[self.date_index + 1]
            view = AddSlotsTimeView(
                dates=self.dates,
                real_event=self.real_event,
                user_tz=self.user_tz,
                guild_id=self.guild_id,
                user=self.user,
                date_index=self.date_index + 1,
            )
            await interaction.response.edit_message(
                content=f"🕐 **Select times to add for {self.real_event.event_name} on {next_date}:**",
                view=view,
            )

    async def _cancel(self, interaction: discord.Interaction):
        view = ManageEventView(self.real_event, self.user_tz, self.guild_id, self.user)
        await interaction.response.edit_message(content="", view=view)
