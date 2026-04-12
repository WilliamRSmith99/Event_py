import discord
from discord.ui import Button, View
from datetime import datetime
from commands.user import timezone
from core import utils, userdata, events, conf
from core.logging import get_logger

logger = get_logger(__name__)

SLOTS_PER_PAGE = 20


def _build_chart_content(event_name: str, sorted_slots: list, page: int, use_24hr: bool) -> str:
    """
    Build the overlap summary message body: best-time banner + ANSI bar chart.

    sorted_slots: list of (date_label, local_dt, utc_iso, signup_map), sorted by count desc.
    """
    if not sorted_slots:
        return f"📊 **{event_name}** — No availability proposed yet."

    # Total unique attendees across all slots
    all_uids: set = set()
    for _, _, _, signup_map in sorted_slots:
        all_uids.update(signup_map.values())
    total_unique = len(all_uids)

    max_count = max(len(s[3]) for s in sorted_slots)

    # Best-time banner (always slot 0 — highest RSVP count)
    _, best_dt, _, best_map = sorted_slots[0]
    best_count = len(best_map)
    pct = int(best_count / total_unique * 100) if total_unique else 0
    best_time_str = utils.format_time(best_dt, use_24hr)
    best_date_str = best_dt.strftime("%a %b %d")
    banner = (
        f"📊 **{event_name}**\n"
        f"⭐ **Best: {best_time_str} {best_date_str}**"
        f" — {best_count}/{total_unique} ({pct}% of respondents)\n"
    )

    # Current page slice
    start = page * SLOTS_PER_PAGE
    page_slots = sorted_slots[start: start + SLOTS_PER_PAGE]

    # ANSI: green ≥75%, yellow 40–74%, red <40% of max
    ansi_rows = []
    for i, (_, local_dt, _, signup_map) in enumerate(page_slots):
        n = start + i + 1
        count = len(signup_map)
        ratio = count / max_count if max_count else 0

        bar_filled = round(ratio * 10)
        bar = "█" * bar_filled + "░" * (10 - bar_filled)

        if ratio >= 0.75:
            color = "\u001b[32m"   # green
        elif ratio >= 0.40:
            color = "\u001b[33m"   # yellow/amber
        else:
            color = "\u001b[31m"   # red
        reset = "\u001b[0m"

        t_str = utils.format_time(local_dt, use_24hr)
        d_str = local_dt.strftime("%a %b %d")
        ansi_rows.append(f"{n:>2}  {d_str}  {t_str}  {color}{bar}{reset}  {count}")

    chart = "```ansi\n" + "\n".join(ansi_rows) + "\n```"
    return banner + chart


class NumberedSlotButton(Button):
    """Numbered button corresponding to a row in the bar chart."""

    def __init__(self, number: int, utc_iso: str, row: int):
        super().__init__(
            label=str(number),
            style=discord.ButtonStyle.primary,
            custom_id=f"slot_{utc_iso}",
            row=row,
        )
        self.utc_iso = utc_iso

    async def callback(self, interaction: discord.Interaction):
        matching_slot = next(
            (s for s in self.view.sorted_slots if s[2] == self.utc_iso), None
        )
        if not matching_slot:
            await interaction.response.edit_message(content="Slot not found.", view=self.view)
            return

        _, local_dt, _, signup_map = matching_slot
        if not signup_map:
            await interaction.response.edit_message(
                content="No users registered for this time slot.", view=self.view
            )
            return

        usernames = []
        for uid in signup_map.values():
            member = interaction.guild.get_member(int(uid))
            usernames.append(member.display_name if member else f"<@{uid}>")

        use_24hr = userdata.get_effective_time_format(interaction.user.id, interaction.guild_id)
        date_str = local_dt.strftime("%B %d")
        time_str = utils.format_time(local_dt, use_24hr)

        # Show confirm button only if event not already confirmed and user has permission
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

        attendee_view = AttendeeView(self.view, self.utc_iso, show_confirm=show_confirm)
        await interaction.response.edit_message(
            content=f"👥 **Users available at {time_str} on {date_str}**:\n- " + "\n- ".join(usernames),
            view=attendee_view,
        )


class PageNavButton(Button):
    """Previous / Next page for the slot list."""

    def __init__(self, parent_view, label: str, direction: int, row: int, disabled: bool = False):
        super().__init__(label=label, style=discord.ButtonStyle.secondary, row=row, disabled=disabled)
        self.parent_view = parent_view
        self.direction = direction  # +1 or -1

    async def callback(self, interaction: discord.Interaction):
        pv = self.parent_view
        view = OverlapSummaryView(
            event=pv.event,
            local_availability=pv.local_availability,
            user_timezone=pv.user_timezone,
            page=pv.page + self.direction,
            show_back_button=pv.show_back_button,
            use_24hr=pv.use_24hr,
        )
        await interaction.response.edit_message(content=view.get_content(), view=view)


class BackToInfoButton(Button):
    def __init__(self, event):
        super().__init__(label="⬅️ Back to Info", style=discord.ButtonStyle.danger, row=4)
        self.event = event

    async def callback(self, interaction: discord.Interaction):
        from commands.event.list import format_single_event
        await format_single_event(interaction, self.event, is_edit=True)


class OverlapSummaryView(View):
    def __init__(
        self,
        event,
        local_availability,
        user_timezone: str,
        page: int = 0,
        show_back_button: bool = False,
        use_24hr: bool = False,
    ):
        super().__init__(timeout=None)
        self.event = event
        self.local_availability = local_availability
        self.user_timezone = user_timezone
        self.page = page
        self.show_back_button = show_back_button
        self.use_24hr = use_24hr

        # Flatten all slots, sort by RSVP count descending
        all_slots = []
        for date_label, slots in local_availability:
            for local_dt, utc_iso, signup_map in slots:
                all_slots.append((date_label, local_dt, utc_iso, signup_map))
        self.sorted_slots = sorted(all_slots, key=lambda s: len(s[3]), reverse=True)

        self.render()

    def get_content(self) -> str:
        return _build_chart_content(
            self.event.event_name, self.sorted_slots, self.page, self.use_24hr
        )

    def render(self):
        self.clear_items()

        start = self.page * SLOTS_PER_PAGE
        page_slots = self.sorted_slots[start: start + SLOTS_PER_PAGE]
        total_pages = max(1, (len(self.sorted_slots) + SLOTS_PER_PAGE - 1) // SLOTS_PER_PAGE)

        # Numbered slot buttons — 5 per row, rows 0–3
        for i, (_, _, utc_iso, _) in enumerate(page_slots):
            n = start + i + 1
            self.add_item(NumberedSlotButton(n, utc_iso, row=i // 5))

        # Row 4: optional back-to-info + page nav (only shown when multiple pages exist)
        if self.show_back_button:
            self.add_item(BackToInfoButton(self.event))

        if total_pages > 1:
            self.add_item(PageNavButton(
                self, "⬅️ Prev", -1, row=4, disabled=self.page == 0
            ))
            self.add_item(PageNavButton(
                self, "Next ➡️", +1, row=4, disabled=self.page >= total_pages - 1
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

        event.confirmed_date = utc_iso
        events.modify_event(event)

        confirmed_dt = datetime.fromisoformat(utc_iso)
        time_display = f"<t:{int(confirmed_dt.timestamp())}:F>"

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

        try:
            from core import bulletins
            await bulletins.update_bulletin_header(interaction.client, event)
        except Exception as e:
            logger.warning(f"Could not update bulletin after confirm: {e}")

        attendee_line = f"\n📬 Notified {notified} registered attendee(s)." if notified else ""
        await interaction.response.edit_message(
            content=f"✅ **{event.event_name}** confirmed for {time_display}!{attendee_line}",
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
        super().__init__(
            label="⬅️ Back", style=discord.ButtonStyle.danger, custom_id="back_button", row=4
        )
        self.original_view = original_view

    async def callback(self, interaction: discord.Interaction):
        ov = self.original_view
        view = OverlapSummaryView(
            ov.event,
            ov.local_availability,
            ov.user_timezone,
            ov.page,
            show_back_button=ov.show_back_button,
            use_24hr=ov.use_24hr,
        )
        await interaction.response.edit_message(content=view.get_content(), view=view)


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
        use_24hr = userdata.get_effective_time_format(interaction.user.id, interaction.guild_id)

        view = OverlapSummaryView(event, local_availability, user_tz_str, use_24hr=use_24hr)
        await interaction.response.send_message(view.get_content(), view=view, ephemeral=True)
    else:
        from commands.event.list import format_single_event
        await interaction.response.send_message(
            f"😬 Unable to match a single event for `{event_name}`.\n"
            "Did you mean one of these?", ephemeral=True)
        for event in event_matches.values():
            await format_single_event(interaction, event, is_edit=False)
