import discord
from commands.user import timezone
from core import utils, events, userdata, bulletins, conf
from core.logging import get_logger, log_event_action
from discord.ui import Button, View
from discord import ButtonStyle

logger = get_logger(__name__)
MAX_TIME_BUTTONS = 20

async def schedule_command(interaction: discord.Interaction, event_name: str, eph_resp: bool = False):
    guild_id = interaction.guild_id
    matches = events.get_events(guild_id, event_name)

    if not matches:
        await interaction.response.send_message("❌ Event not found.", ephemeral=True)
        return

    if len(matches) > 1:
        # Multiple matches - show them all in upcoming_events format
        from commands.event import list as event_list
        await interaction.response.send_message(
            f"😬 Unable to match a single event for `{event_name}`.\nDid you mean one of these?",
            ephemeral=True
        )
        for event in matches.values():
            await event_list.format_single_event(interaction, event, is_edit=False)
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

    # Check if event has a confirmed date (single slot) - toggle registration directly
    if event.confirmed_date and event.confirmed_date != "TBD":
        await _toggle_single_slot_registration(interaction, event, eph_resp)
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

    # Get time format preference
    server_config = conf.get_config(interaction.guild_id)
    use_24hr = getattr(server_config, "use_24hr_time", False)

    view = PaginatedHourSelectionView(event, local_slots_by_date, str(interaction.user.id), use_24hr=use_24hr)

    try:
        if interaction.type.name == "component" and not eph_resp:
            await interaction.response.edit_message(content=view.render_date_label(), view=view)
        else:
            await interaction.response.send_message(content=view.render_date_label(), view=view, ephemeral=True)
    except discord.HTTPException as e:
        await interaction.followup.send(f"❌ Failed to display schedule view: {str(e)}", ephemeral=True)


async def _toggle_single_slot_registration(interaction: discord.Interaction, event, eph_resp: bool = False):
    """Toggle registration for a confirmed event with a single time slot."""
    user_id = str(interaction.user.id)
    confirmed_slot = event.confirmed_date

    # Check if user is currently registered for this slot
    slot_availability = event.availability.get(confirmed_slot, {})
    is_registered = user_id in slot_availability.values()

    if is_registered:
        # Unregister user
        updated_queue = events.remove_user_from_queue(slot_availability, user_id)
        event.availability[confirmed_slot] = updated_queue
        # Remove from RSVP if no longer has any availability
        if not events.user_has_any_availability(user_id, event.availability) and user_id in event.rsvp:
            event.rsvp.remove(user_id)
        action_msg = f"❌ You have been **unregistered** from **{event.event_name}**."
    else:
        # Register user
        next_position = str(len(slot_availability) + 1)
        if confirmed_slot not in event.availability:
            event.availability[confirmed_slot] = {}
        event.availability[confirmed_slot][next_position] = user_id
        # Add to RSVP if not already there
        if user_id not in event.rsvp:
            event.rsvp.append(user_id)
        action_msg = f"✅ You have been **registered** for **{event.event_name}**!"

    # Save changes
    events.modify_event(event)
    log_event_action("register", event.guild_id, event.event_name, user_id=int(user_id))

    # Update bulletin if exists
    try:
        event_msg_directory = bulletins.get_event_bulletin(guild_id=event.guild_id)
        if event.bulletin_message_id and event_msg_directory.get(f"{event.bulletin_message_id}"):
            await bulletins.update_bulletin_header(interaction.client, event)
    except Exception as e:
        logger.warning(f"Failed to update bulletin: {e}")

    # Send response
    if eph_resp:
        await interaction.response.send_message(action_msg, ephemeral=True)
    else:
        await utils.safe_send(interaction, action_msg)    

class PaginatedHourSelectionView(View):
    def __init__(self, event, slots_data_by_date, user_id, use_24hr: bool = False):
        super().__init__(timeout=900)
        self.event = event
        self.user_id = user_id
        self.page = 0
        self.current_date_index = 0
        self.selected_utc_keys = set()
        self.use_24hr = use_24hr

        self.date_objs = []
        self.slots_by_date = []

        for date_label, slots in slots_data_by_date:
            processed_slots = []
            for local_dt, utc_iso_str, users in slots:
                date_key = local_dt.strftime("%A, %m/%d/%y")
                hour_key = utils.format_hour(local_dt, use_24hr)
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

        # Update RSVP list safely
        has_availability = events.user_has_any_availability(view.user_id, view.event.availability)
        user_in_rsvp = view.user_id in view.event.rsvp

        if has_availability and not user_in_rsvp:
            view.event.rsvp.append(view.user_id)
            changed = True
        elif not has_availability and user_in_rsvp:
            view.event.rsvp.remove(view.user_id)
            changed = True

        # Always save and provide feedback
        event_data = view.event

        if changed:
            log_event_action("register", event_data.guild_id, event_data.event_name, user_id=int(view.user_id))
            events.modify_event(event_data)

            # Try to update bulletin if it exists (non-blocking)
            try:
                event_msg_directory = bulletins.get_event_bulletin(guild_id=event_data.guild_id)
                if event_data.bulletin_message_id and event_msg_directory.get(f"{event_data.bulletin_message_id}"):
                    event_bulletin_msg = event_msg_directory[f"{event_data.bulletin_message_id}"]
                    thread = interaction.client.get_channel(int(event_bulletin_msg.thread_id))

                    if thread:
                        for msg_id in event_bulletin_msg.thread_messages:
                            try:
                                message = await thread.fetch_message(int(msg_id))
                                new_embed = bulletins.generate_single_embed_for_message(event_data, str(message.id))
                                if new_embed:
                                    bulletin_view = bulletins.ThreadView(event_data.event_name, [
                                        (info["embed_index"], slot)
                                        for slot, info in event_data.availability_to_message_map.items()
                                        if info["message_id"] == str(message.id)
                                    ])
                                    await message.edit(embed=new_embed, view=bulletin_view)
                            except discord.NotFound:
                                logger.warning(f"Bulletin message {msg_id} not found")

                        # Update main bulletin head message
                        await bulletins.update_bulletin_header(interaction.client, event_data)
            except Exception as e:
                logger.warning(f"Failed to update bulletin: {e}")

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
