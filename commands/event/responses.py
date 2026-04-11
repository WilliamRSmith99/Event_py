import discord
from discord.ui import Button, View
from datetime import datetime
from commands.user import timezone
from core import utils, userdata, events, conf
from core.logging import get_logger

logger = get_logger(__name__)
MAX_DATES_PER_PAGE = 4
MAX_TIME_BUTTONS_PER_ROW = 4

async def build_overlap_summary(interaction: discord.Interaction, event_name: str, guild_id: str):
    user_tz_str = userdata.get_user_timezone(interaction.user.id)
    if not user_tz_str:
        await utils.safe_send(
            interaction,
            "❌ **Timezone Required**\n\nSelect your timezone below to continue:",
            view=timezone.RegionSelectView(interaction.user.id)
        )
        return

    event_matches = events.get_events(guild_id, event_name)
    if len(event_matches) == 0:
        await interaction.response.send_message("❌ Event not found.", ephemeral=True)
        return
    elif len(event_matches) == 1:
        event = list(event_matches.values())[0]
        local_availability = utils.from_utc_to_local(event.availability, user_tz_str)

        # Get user's effective time format preference
        use_24hr = userdata.get_effective_time_format(interaction.user.id, interaction.guild_id)

        view = OverlapSummaryView(event, local_availability, user_tz_str, use_24hr=use_24hr)
        await interaction.response.send_message(
            f"📊 Top availability slots for **{event.event_name}**", view=view, ephemeral=True)
    else:
        from commands.event.list import format_single_event
        await interaction.response.send_message(
            f"😬 Unable to match a single event for `{event_name}`.\n"
            "Did you mean one of these?", ephemeral=True)
        for event in event_matches.values():
            await format_single_event(interaction, event, is_edit=False)

class OverlapSummaryButton(Button):
    def __init__(self, label: str, utc_iso: str, row: int):
        super().__init__(
            label=label,
            style=discord.ButtonStyle.primary,
            custom_id=f"show_attendees_{utc_iso}",
            row=row
        )
        self.datetime_iso = utc_iso

    async def callback(self, interaction: discord.Interaction):
        matching_slot = next((s for s in self.view.all_slots if s[2] == self.datetime_iso), None)

        if not matching_slot:
            await interaction.response.edit_message(content="Slot not found.", view=self.view)
            return

        _, local_dt, _, signup_map = matching_slot
        if not signup_map:
            await interaction.response.edit_message(content="No users registered for this time slot.", view=self.view)
            return

        usernames = []
        for uid in signup_map.values():
            member = interaction.guild.get_member(int(uid))
            usernames.append(member.display_name if member else f"<@{uid}>")

        date_str = local_dt.strftime("%B %d")
        use_24hr = userdata.get_effective_time_format(interaction.user.id, interaction.guild_id)
        time_str = utils.format_time(local_dt, use_24hr)

        # Determine if the viewer can confirm this slot.
        # Hide confirm button if a date is already confirmed.
        event = self.view.event
        already_confirmed = bool(event.confirmed_date and event.confirmed_date != "TBD")
        show_confirm = False
        if not already_confirmed:
            show_confirm = interaction.user.id == event.organizer
            if not show_confirm:
                from core.permissions import has_permission, PermissionLevel
                from core.conf import get_config
                guild_config = get_config(interaction.guild_id)
                show_confirm = has_permission(interaction.user, guild_config, PermissionLevel.ADMIN)

        attendee_view = AttendeeView(self.view, self.datetime_iso, show_confirm=show_confirm)
        await interaction.response.edit_message(
            content=f"👥 **Users available at {time_str} on {date_str}**:\n- " + "\n- ".join(usernames),
            view=attendee_view
        )

class NavButton(Button):
    def __init__(self, parent_view, label: str, nav_type: str, event, row: int, user_timezone: str, disabled=False):
        super().__init__(label=label, style=discord.ButtonStyle.secondary, row=row, disabled=disabled)
        self.parent_view = parent_view
        self.nav_type = nav_type
        self.event = event
        self.user_timezone = user_timezone

    async def callback(self, interaction: discord.Interaction):
    # First, adjust values
        date_page = self.parent_view.date_page
        time_page = self.parent_view.time_page

        if self.nav_type == "next_date":
            date_page += 1
        elif self.nav_type == "prev_date":
            date_page -= 1
        elif self.nav_type == "later":
            time_page += 1
        elif self.nav_type == "earlier":
            time_page -= 1

        # Clamp values
        total_date_pages = (len(self.parent_view.date_slots) - 1) // MAX_DATES_PER_PAGE + 1
        date_page = max(0, min(date_page, total_date_pages - 1))

        # Compute visible dates
        start_idx = date_page * MAX_DATES_PER_PAGE
        end_idx = start_idx + MAX_DATES_PER_PAGE
        visible_dates = self.parent_view.date_slots[start_idx:end_idx]

        # Compute max time slots among these visible dates only
        max_slots_visible = max((len(slots) for _, slots in visible_dates), default=0)
        total_time_pages = (max_slots_visible - 1) // MAX_TIME_BUTTONS_PER_ROW + 1 if max_slots_visible > 0 else 1
        time_page = max(0, min(time_page, total_time_pages - 1))

        # Re-render with updated pages
        view = OverlapSummaryView(
            event=self.event,
            local_availability=self.parent_view.local_availability,
            user_timezone=self.user_timezone,
            date_page=date_page,
            time_page=time_page,
            show_back_button=self.parent_view.show_back_button,
            use_24hr=self.parent_view.use_24hr
        )

        await interaction.response.edit_message(
            content=f"📊 Top availability slots for **{self.event.event_name}**",
            view=view
        )

class BackToInfoButton(Button):
    def __init__(self, event):
        super().__init__(label="⬅️ Back to Info", style=discord.ButtonStyle.danger, row=4)
        self.event = event

    async def callback(self, interaction: discord.Interaction):
        from commands.event.list import format_single_event
        await format_single_event(interaction, self.event, is_edit=True)

class OverlapSummaryView(View):
    def __init__(self, event, local_availability, user_timezone: str, date_page: int = 0, time_page: int = 0, show_back_button: bool = False, use_24hr: bool = False):
        super().__init__(timeout=None)
        self.event = event
        self.local_availability = local_availability
        self.user_timezone = user_timezone
        self.date_page = date_page
        self.time_page = time_page
        self.show_back_button = show_back_button
        self.use_24hr = use_24hr

        self.date_slots = []
        self.all_slots = []

        for date_label, slots in self.local_availability:
            slot_data = []
            for local_dt, utc_iso, signup_map in slots:
                slot_data.append((local_dt, utc_iso, signup_map))
                self.all_slots.append((date_label, local_dt, utc_iso, signup_map))
            self.date_slots.append((date_label, slot_data))

        self.total_date_pages = (len(self.date_slots) - 1) // MAX_DATES_PER_PAGE + 1
        self.render()

    def render(self):
        self.clear_items()
        self.total_date_pages = (len(self.date_slots) - 1) // MAX_DATES_PER_PAGE + 1
        logger.debug(f"Rendering overlap view: page={self.date_page}, total={self.total_date_pages}, date_slots={len(self.date_slots)}")

        start_idx = self.date_page * MAX_DATES_PER_PAGE
        end_idx = start_idx + MAX_DATES_PER_PAGE
        visible_dates = self.date_slots[start_idx:end_idx]

        time_start = self.time_page * MAX_TIME_BUTTONS_PER_ROW
        time_end = time_start + MAX_TIME_BUTTONS_PER_ROW

        for row_index, (date_label, slots) in enumerate(visible_dates):
            self.add_item(Button(label=date_label, style=discord.ButtonStyle.secondary, disabled=True, row=row_index))

            sorted_slots = sorted(slots, key=lambda s: len(s[2]), reverse=True)
            paginated_slots = sorted_slots[time_start:time_end]

            for local_dt, utc_iso, signup_map in paginated_slots:
                time_str = utils.format_time(local_dt, self.use_24hr)
                label = f"{time_str} ({len(signup_map)})"
                self.add_item(OverlapSummaryButton(label, utc_iso, row=row_index))

        nav_row = 4
        if self.show_back_button:
            self.add_item(BackToInfoButton(self.event))

        # Determine max number of time slots across *any* date to paginate horizontally
        max_slots = max((len(slots) for _, slots in self.date_slots), default=0)
        total_time_pages = (max_slots - 1) // MAX_TIME_BUTTONS_PER_ROW + 1 if max_slots > 0 else 1

        total_date_pages = (len(self.date_slots) - 1) // MAX_DATES_PER_PAGE + 1

        # --- Nav buttons ---
        self.add_item(NavButton(
            self, "⬅️ Prev Date", "prev_date", self.event,
            row=nav_row,
            user_timezone=self.user_timezone,
            disabled=self.date_page == 0
        ))

        # Time slot navs use visible dates
        max_slots = max((len(slots) for _, slots in visible_dates), default=0)
        total_time_pages = (max_slots - 1) // MAX_TIME_BUTTONS_PER_ROW + 1 if max_slots > 0 else 1

        self.add_item(NavButton(
            self, "⬅️ Earlier Times", "earlier", self.event,
            row=nav_row,
            user_timezone=self.user_timezone,
            disabled=self.time_page == 0
        ))
        self.add_item(NavButton(
            self, "Later Times ➡️", "later", self.event,
            row=nav_row,
            user_timezone=self.user_timezone,
            disabled=self.time_page >= total_time_pages - 1
        ))
        self.add_item(NavButton(
            self, "Next Date ➡️", "next_date", self.event,
            row=nav_row,
            user_timezone=self.user_timezone,
            disabled=self.date_page >= total_date_pages - 1
        ))

class ConfirmSlotButton(Button):
    """Organizer/admin-only button to set this slot as the confirmed event time."""

    def __init__(self):
        super().__init__(
            label="✅ Confirm this time",
            style=discord.ButtonStyle.success,
            custom_id="confirm_slot",
            row=4,
        )

    async def callback(self, interaction: discord.Interaction):
        view: "AttendeeView" = self.view
        event = view.original_view.event
        utc_iso = view.datetime_iso

        # Runtime permission check (guard against someone forwarding the message etc.)
        is_allowed = interaction.user.id == event.organizer
        if not is_allowed:
            from core.permissions import has_permission, PermissionLevel
            from core.conf import get_config
            guild_config = get_config(interaction.guild_id)
            is_allowed = has_permission(interaction.user, guild_config, PermissionLevel.ADMIN)

        if not is_allowed:
            await interaction.response.edit_message(
                content="❌ Only the event organizer or a server admin can confirm a time.",
                view=view,
            )
            return

        # Commit the confirmed date
        event.confirmed_date = utc_iso
        events.modify_event(event)

        confirmed_dt = datetime.fromisoformat(utc_iso)
        time_display = f"<t:{int(confirmed_dt.timestamp())}:F>"

        # Notify all RSVPed users
        notified = 0
        try:
            from core.notifications import notify_event_confirmed
            notified = await notify_event_confirmed(
                interaction.client,
                int(event.guild_id),
                event.event_name,
                confirmed_dt,
            )
        except Exception as e:
            logger.warning(f"Could not send confirmation notifications: {e}")

        # Update bulletin header if one exists
        try:
            from core import bulletins
            await bulletins.update_bulletin_header(interaction.client, event)
        except Exception as e:
            logger.warning(f"Could not update bulletin after confirm: {e}")

        attendee_line = f"\n📬 Notified {notified} registered attendee(s)." if notified else ""
        await interaction.response.edit_message(
            content=(
                f"✅ **{event.event_name}** confirmed for {time_display}!{attendee_line}"
            ),
            view=None,
        )


class AttendeeView(View):
    def __init__(self, original_view: OverlapSummaryView, utc_iso: str, show_confirm: bool = False):
        super().__init__(timeout=None)
        self.original_view = original_view
        self.datetime_iso = utc_iso

        if show_confirm:
            self.add_item(ConfirmSlotButton())

        self.add_item(BackButton(original_view))


class BackButton(Button):
    def __init__(self, original_view: OverlapSummaryView):
        super().__init__(label="⬅️ Back", style=discord.ButtonStyle.danger, custom_id="back_button", row=4)
        self.original_view = original_view

    async def callback(self, interaction: discord.Interaction):
        ov = self.original_view
        await interaction.response.edit_message(
            content=f"📊 Top availability slots for **{ov.event.event_name}**",
            view=OverlapSummaryView(
                ov.event,
                ov.local_availability,
                ov.user_timezone,
                ov.date_page,
                ov.time_page,
                show_back_button=ov.show_back_button,
                use_24hr=ov.use_24hr,
            ),
        )

