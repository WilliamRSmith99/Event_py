import discord
from commands.user import timezone
from core import utils, events, userdata, bulletins
from core.logging import get_logger, log_event_action
from discord.ui import Button, View
from discord import ButtonStyle

logger = get_logger(__name__)
MAX_TIME_BUTTONS = 20

async def schedule_command(interaction: discord.Interaction, event_name: str, eph_resp: bool = False):
    guild_id = interaction.guild_id
    matches = events.get_events(guild_id, event_name)

    if not matches or len(matches) != 1:
        await interaction.response.send_message("❌ Event not found.", ephemeral=True)
        return

    event = list(matches.values())[0]
    if not event or not event.availability:
        if eph_resp:
            await interaction.response.send_message(f"📅 No time slots have been proposed for **{event.event_name}** yet.", ephemeral=True)
            return
        else:
            await utils.safe_send(interaction, f"📅 No time slots have been proposed for **{event.event_name}** yet.")
            return

    user_tz_str = userdata.get_user_timezone(interaction.user.id)
    if not user_tz_str:
        if eph_resp:
            await interaction.response.send_message(
                "❌ **Timezone Required**\n\nSelect your timezone below to continue:",
                view=timezone.RegionSelectView(interaction.user.id),
                ephemeral=True
            )
            return
        else:
            await utils.safe_send(
                interaction,
                "❌ **Timezone Required**\n\nSelect your timezone below to continue:",
                view=timezone.RegionSelectView(interaction.user.id)
            )
            return

    local_slots_by_date = utils.from_utc_to_local(event.availability, user_tz_str)

    if not local_slots_by_date:
        if eph_resp:
            await interaction.response.send_message(
                f"📅 No time slots available for **{event.event_name}**.",
                ephemeral=True
            )
            return
        else:
            await utils.safe_send(
                interaction,
                f"📅 No time slots available for **{event.event_name}**."
            )
            return

    view = PaginatedHourSelectionView(event, local_slots_by_date, str(interaction.user.id))

    try:
        if interaction.type.name == "component" and not eph_resp:
            await interaction.response.edit_message(content=view.render_date_label(), view=view)
        else:
            await interaction.response.send_message(content=view.render_date_label(), view=view, ephemeral=True)
    except discord.HTTPException as e:
        await interaction.followup.send(f"❌ Failed to display schedule view: {str(e)}", ephemeral=True)    

class PaginatedHourSelectionView(View):
    def __init__(self, event, slots_data_by_date, user_id):
        super().__init__(timeout=900)
        self.event = event
        self.user_id = user_id
        self.page = 0
        self.current_date_index = 0
        self.selected_utc_keys = set()

        self.date_objs = [] 
        self.slots_by_date = []

        for date_label, slots in slots_data_by_date:
            processed_slots = []
            for local_dt, utc_iso_str, users in slots:
                date_key = local_dt.strftime("%A, %m/%d/%y")
                hour_key = local_dt.strftime("%-I %p")
                processed_slots.append((utc_iso_str, local_dt, date_key, hour_key, users))

                if user_id in users.values():
                    self.selected_utc_keys.add((utc_iso_str, date_key, hour_key))

            self.date_objs.append(date_label)
            self.slots_by_date.append(processed_slots)

        self.render_buttons()

    def render_date_label(self):
        date_label = self.date_objs[self.current_date_index]
        return f"📅 **{date_label} (Your Time)**"

    def render_buttons(self):
        self.clear_items()
        slots = self.slots_by_date[self.current_date_index]
        start = self.page * MAX_TIME_BUTTONS
        end = start + MAX_TIME_BUTTONS

        for utc_iso_str, local_dt, date_key, hour_key, users in slots[start:end]:
            selected = (utc_iso_str, date_key, hour_key) in self.selected_utc_keys
            count = len(users)
            self.add_item(LocalizedHourToggleButton(utc_iso_str, local_dt, date_key, hour_key, selected, count))

        total_pages = (len(slots) - 1) // MAX_TIME_BUTTONS

        # Navigation row
        self.add_item(NavButton("⬅️ Prev Date", "prev_date", disabled=self.current_date_index == 0))
        self.add_item(NavButton("⬅️ Earlier Times", "earlier", disabled=self.page == 0))
        self.add_item(SubmitAllButton())
        self.add_item(NavButton("Later Times ➡️", "later", disabled=self.page >= total_pages))
        self.add_item(NavButton("Next Date ➡️", "next_date", disabled=self.current_date_index >= len(self.date_objs) - 1))


class LocalizedHourToggleButton(Button):
    def __init__(self, utc_iso_str, local_dt, date_key, hour_key, is_selected, attendee_count):
        self.utc_iso_str  = utc_iso_str
        self.utc_date_key = date_key
        self.utc_hour_key = hour_key
        label = f"{hour_key}  [👥 {attendee_count}]" if attendee_count else hour_key
        style = ButtonStyle.success if is_selected else ButtonStyle.secondary

        super().__init__(label=label, style=style, custom_id=f"toggle_{date_key}_{hour_key}")

    async def callback(self, interaction):
        view: PaginatedHourSelectionView = self.view
        key = (self.utc_iso_str, self.utc_date_key, self.utc_hour_key)
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

        selected = view.selected_utc_keys.copy()
        selected_utc_iso_strs = [iso_str for iso_str, _, _ in selected]
        for utc_iso_str in selected_utc_iso_strs:
            user_list = view.event.availability.get(utc_iso_str, {})
            if view.user_id not in user_list.values():
                next_position = str(len(user_list) + 1) 
                view.event.availability[utc_iso_str][next_position] = view.user_id
                changed = True
         
        for utc_iso_str, user_dict in view.event.availability.items():
            if utc_iso_str not in selected_utc_iso_strs and view.user_id in user_dict.values():
                updated_queue = events.remove_user_from_queue(user_dict, view.user_id)
                view.event.availability[utc_iso_str] = updated_queue
                changed = True

        if events.user_has_any_availability(view.user_id, view.event.availability):
            view.event.rsvp.append(view.user_id)
        else:
            view.event.rsvp.remove(view.user_id)

        if changed:
            log_event_action("register", view.event.guild_id, view.event.event_name, user_id=int(view.user_id))
            events.modify_event(view.event)
            # Get message info for this slot
            event_msg_directory = bulletins.get_event_bulletin(guild_id=view.event.guild_id)
            if not view.event.bulletin_message_id or not event_msg_directory.get(f"{view.event.bulletin_message_id}",False):
                return await interaction.response.send_message("Failed to locate bulletin message.", ephemeral=True)
            event_data = view.event
            event_bulletin_msg = event_msg_directory[f"{event_data.bulletin_message_id}"]
            thread = interaction.client.get_channel(int(event_bulletin_msg.thread_id))
            for msg, slots in event_bulletin_msg.thread_messages.items():
                message = await thread.fetch_message(int(msg))

                new_embed = bulletins.generate_single_embed_for_message(event_data, str(message.id))
                if new_embed:
                    # Rebuild the view (button rows) for this embed
                    view = bulletins.ThreadView(event_data.event_name, [
                        (info["embed_index"], slot)
                        for slot, info in event_data.availability_to_message_map.items()
                        if info["message_id"] == str(message.id)
                    ])
                    await message.edit(embed=new_embed, view=view)

                # Update main bulletin head message
                await bulletins.update_bulletin_header(interaction.client, event_data)

                # Save updated events
                events.modify_event(event_data)

        await interaction.response.edit_message(
            content=f"✅ Availability updated for **{event_data.event_name}**.",
            view=None
        )
        view.stop()


class NavButton(Button):
    def __init__(self, label, action, disabled=False):
        super().__init__(label=label, style=ButtonStyle.secondary, row=4, custom_id=f"nav_{action}", disabled=disabled)

    async def callback(self, interaction):
        view: PaginatedHourSelectionView = self.view
        action = self.custom_id.replace("nav_", "")
        slots = view.slots_by_date[view.current_date_index]
        total_pages = (len(slots) - 1) // MAX_TIME_BUTTONS

        if action == "prev_date" and view.current_date_index > 0:
            view.current_date_index -= 1
            view.page = 0
        elif action == "next_date" and view.current_date_index < len(view.date_objs) - 1:
            view.current_date_index += 1
            view.page = 0
        elif action == "earlier" and view.page > 0:
            view.page -= 1
        elif action == "later" and view.page < total_pages:
            view.page += 1

        view.render_buttons()
        await interaction.response.edit_message(view=view, content=view.render_date_label())
