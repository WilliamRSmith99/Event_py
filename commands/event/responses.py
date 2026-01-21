import discord
from discord.ui import Button, View
from commands.user import timezone
from core import utils, userdata, events
from core.logging import get_logger

logger = get_logger(__name__)
MAX_DATES_PER_PAGE = 4
MAX_TIME_BUTTONS_PER_ROW = 4

async def build_overlap_summary(interaction: discord.Interaction, event_name: str, guild_id: str):
    user_tz_str = userdata.get_user_timezone(interaction.user.id)
    if not user_tz_str:
        await utils.safe_send(
            interaction,
            "❌ Please set your timezone using `/settimezone` first!",
            view=timezone.RegionSelectView(interaction.user.id)
        )
        return

    event_matches = events.get_events(guild_id, event_name)
    if len(event_matches) == 0:
        return None, "❌ Event not found."
    elif len(event_matches) == 1:
        event = list(event_matches.values())[0]
        local_availability = utils.from_utc_to_local(event.availability, user_tz_str)
        view = OverlapSummaryView(event, local_availability, user_tz_str)
        await interaction.response.send_message(
            f"📊 Top availability slots for **{event.event_name}**", view=view, ephemeral=True)
    else:
        from commands.event.list import format_single_event
        await interaction.response.send_message(
            f"😬 Oh no! An exact match couldn't be located for `{event_name}`.\n"
            "Did you mean one of these?", ephemeral=True)
        await interaction.response.defer(ephemeral=True, thinking=True)
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
        time_str = local_dt.strftime("%I:%M %p").lstrip("0")

        attendee_view = AttendeeView(self.view, self.datetime_iso)
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
            show_back_button=self.parent_view.show_back_button
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
    def __init__(self, event, local_availability, user_timezone: str, date_page: int = 0, time_page: int = 0, show_back_button: bool = False):
        super().__init__(timeout=None)
        self.event = event
        self.local_availability = local_availability
        self.user_timezone = user_timezone
        self.date_page = date_page
        self.time_page = time_page
        self.show_back_button = show_back_button

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
                time_str = local_dt.strftime("%I:%M %p").lstrip("0")
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
        # # Nav buttons
        # self.add_item(NavButton(self, "⬅️ Prev Date", "prev_date", self.event, row=nav_row, user_timezone=self.user_timezone, disabled=self.date_page == 0))
        # self.add_item(NavButton(self, "⬅️ Earlier Times", "earlier", self.event, row=nav_row, user_timezone=self.user_timezone, disabled=self.time_page == 0))
        # self.add_item(NavButton(self, "Later Times ➡️", "later", self.event, row=nav_row, user_timezone=self.user_timezone, disabled=self.time_page >= total_time_pages - 1))
        # self.add_item(NavButton(self, "Next Date ➡️", "next_date", self.event, row=nav_row, user_timezone=self.user_timezone, disabled=self.date_page >= ((len(self.date_slots) - 1) // MAX_DATES_PER_PAGE)))

class AttendeeView(View):
    def __init__(self, original_view: OverlapSummaryView, utc_iso: str):
        super().__init__(timeout=None)
        self.original_view = original_view
        self.datetime_iso = utc_iso

    @discord.ui.button(label="Back", style=discord.ButtonStyle.danger, custom_id="back_button", row=4)
    async def back(self, interaction: discord.Interaction, button: Button):
        await interaction.response.edit_message(
            content=f"📊 Top availability slots for **{self.original_view.event.event_name}**",
            view=OverlapSummaryView(
                self.original_view.event,
                self.original_view.local_availability,
                self.original_view.user_timezone,
                self.original_view.date_page,
                self.original_view.time_page,
                show_back_button=self.original_view.show_back_button
            )
        )

