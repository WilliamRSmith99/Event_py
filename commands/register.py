from database import events, shared, user_data
from commands.timezone import timezone 
import discord
from datetime import datetime, date 
from discord.ui import Button, View
from discord import ButtonStyle
import pytz 
from collections import defaultdict 
from database.events import parse_utc_availability_key

MAX_TIME_BUTTONS = 20

async def schedule_command(interaction: discord.Interaction, event_name: str):
    guild_id = str(interaction.guild_id)
    full_event_name = events.resolve_event_name(guild_id, event_name)
    if not full_event_name:
        await interaction.response.send_message("❌ Event not found.", ephemeral=True)
        return

    event = events.get_event(guild_id, full_event_name)
    if not event:
        await shared.safe_respond(interaction, "⚠️ Event data missing.", ephemeral=True)
        return

    user_tz_str = user_data.get_user_timezone(interaction.user.id)
    if not user_tz_str:
        await shared.safe_respond(
            interaction,
            "❌ Please set your timezone using `/settimezone` first!",
            ephemeral=True,
            view=timezone.RegionSelectView(interaction.user.id)
        )
        return
    try:
        user_tz = pytz.timezone(user_tz_str)
    except pytz.UnknownTimeZoneError:
        await shared.safe_respond(
            interaction,
            f"❌ Invalid timezone stored: {user_tz_str}. Please reset it using `/settimezone`.",
            ephemeral=True
        )
        return

    local_slots_by_date = defaultdict(list)
    if not event.availability:
        await shared.safe_respond(
            interaction,
            f"📅 No time slots have been proposed for **{event.event_name}** yet.",
            ephemeral=True
        )
        return

    for utc_date_key, hours_dict in event.availability.items():
        for utc_hour_key in hours_dict:
            utc_dt = parse_utc_availability_key(utc_date_key, utc_hour_key)
            if utc_dt:
                local_dt = utc_dt.astimezone(user_tz)
                local_date_obj = local_dt.date()
                local_slots_by_date[local_date_obj].append((local_dt, utc_date_key, utc_hour_key))

    if not local_slots_by_date:
        await shared.safe_respond(
            interaction,
            f"📅 No time slots have been proposed for **{event.event_name}** yet.",
            ephemeral=True
        )
        return

    sorted_local_dates = sorted(local_slots_by_date.keys())
    slots_by_date = [sorted(local_slots_by_date[d], key=lambda x: x[0]) for d in sorted_local_dates]

    view = PaginatedHourSelectionView(event, sorted_local_dates, slots_by_date, str(interaction.user.id))

    try:
        if interaction.type.name == "component":
            await interaction.response.edit_message(content=view.render_date_label(), view=view)
        else:
            await interaction.response.send_message(content=view.render_date_label(), view=view, ephemeral=True)
    except discord.HTTPException as e:
        await interaction.followup.send(f"❌ Failed to display schedule view: {str(e)}", ephemeral=True)


class PaginatedHourSelectionView(View):
    def __init__(self, event, date_objs, slots_data_by_date, user_id):
        super().__init__(timeout=900)
        self.event = event
        self.date_objs = date_objs
        self.slots_by_date = slots_data_by_date
        self.user_id = user_id
        self.current_date_index = 0
        self.page = 0
        self.selected_utc_keys = set()

        for date_slots in self.slots_by_date:
            for _, date_key, hour_key in date_slots:
                if user_id in event.availability.get(date_key, {}).get(hour_key, []):
                    self.selected_utc_keys.add((date_key, hour_key))

        self.render_buttons()

    def render_date_label(self):
        return f"📅 **{self.date_objs[self.current_date_index].strftime('%A, %B %d, %Y')} (Your Time)**"

    def render_buttons(self):
        self.clear_items()
        slots = self.slots_by_date[self.current_date_index]
        start = self.page * MAX_TIME_BUTTONS
        end = start + MAX_TIME_BUTTONS
        for local_dt, date_key, hour_key in slots[start:end]:
            selected = (date_key, hour_key) in self.selected_utc_keys
            count = len(self.event.availability.get(date_key, {}).get(hour_key, []))
            self.add_item(LocalizedHourToggleButton(local_dt, date_key, hour_key, selected, count))

        total_pages = (len(slots) - 1) // MAX_TIME_BUTTONS
        self.add_item(NavButton("⬅️ Prev Date", "prev_date", disabled=self.current_date_index == 0))
        self.add_item(NavButton("⬅️ Earlier Times", "earlier", disabled=self.page == 0))
        self.add_item(SubmitAllButton())
        self.add_item(NavButton("Later Times ➡️", "later", disabled=self.page == total_pages))
        self.add_item(NavButton("Next Date ➡️", "next_date", disabled=self.current_date_index == len(self.date_objs) - 1))

class LocalizedHourToggleButton(Button):
    def __init__(self, local_dt, date_key, hour_key, is_selected, attendee_count):
        self.utc_date_key = date_key
        self.utc_hour_key = hour_key
        hour_label = local_dt.strftime("%I:%M %p").lstrip("0")
        label = f"{hour_label}  [👥 {attendee_count}]" if attendee_count else hour_label
        super().__init__(
            label=label,
            style=ButtonStyle.success if is_selected else ButtonStyle.secondary,
            custom_id=f"toggle_{date_key}_{hour_key}"
        )

    async def callback(self, interaction):
        view: PaginatedHourSelectionView = self.view
        key = (self.utc_date_key, self.utc_hour_key)
        if key in view.selected_utc_keys:
            view.selected_utc_keys.remove(key)
            self.style = ButtonStyle.secondary
        else:
            view.selected_utc_keys.add(key)
            self.style = ButtonStyle.success
        view.render_buttons()
        await interaction.response.edit_message(view=view, content=view.render_date_label())

class SubmitAllButton(Button):
    def __init__(self):
        super().__init__(label="✅ Submit Times", style=ButtonStyle.primary, row=4)

    async def callback(self, interaction):
        view: PaginatedHourSelectionView = self.view
        changed = False
        for date_key, hour_key in [(k[0], k[1]) for k in view.selected_utc_keys]:
            if date_key not in view.event.availability or hour_key not in view.event.availability[date_key]:
                continue
            user_list = view.event.availability[date_key][hour_key]
            if view.user_id not in user_list:
                user_list.add(view.user_id)
                changed = True

        # Clear unselected
        for date_key, hour_dict in view.event.availability.items():
            for hour_key, user_list in hour_dict.items():
                if (date_key, hour_key) not in view.selected_utc_keys and view.user_id in user_list:
                    user_list.remove(view.user_id)
                    changed = True

        if user_has_any_availability(view.user_id, view.event.availability):
            view.event.rsvp.add(view.user_id)
        else:
            view.event.rsvp.discard(view.user_id)

        if changed:
            events.modify_event(view.event)

        await interaction.response.edit_message(content=f"✅ Availability updated for **{view.event.event_name}**.", view=None)
        view.stop()

class NavButton(Button):
    def __init__(self, label, action, disabled=False):
        super().__init__(label=label, style=ButtonStyle.secondary, row=4, custom_id=f"nav_{action}", disabled=disabled)

    async def callback(self, interaction):
        view: PaginatedHourSelectionView = self.view
        slots = view.slots_by_date[view.current_date_index]
        total_pages = (len(slots) - 1) // MAX_TIME_BUTTONS
        if self.custom_id == "nav_prev_date" and view.current_date_index > 0:
            view.current_date_index -= 1
            view.page = 0
        elif self.custom_id == "nav_next_date" and view.current_date_index < len(view.date_objs) - 1:
            view.current_date_index += 1
            view.page = 0
        elif self.custom_id == "nav_earlier" and view.page > 0:
            view.page -= 1
        elif self.custom_id == "nav_later" and view.page < total_pages:
            view.page += 1
        view.render_buttons()
        await interaction.response.edit_message(view=view, content=view.render_date_label())

def user_has_any_availability(user_id: str, availability: dict) -> bool:
    for date_slots in availability.values():
        for user_list in date_slots.values():
            if user_id in user_list:
                return True
    return False
