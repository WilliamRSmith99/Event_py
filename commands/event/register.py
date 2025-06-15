import discord
from commands.user import timezone
from core import utils, events, userdata, bulletins, auth, conf
from commands.event import lists
from discord.ui import Button, View
from discord import ButtonStyle

MAX_TIME_BUTTONS = 12  # 3 rows × 4 buttons

async def schedule_command(interaction: discord.Interaction, event_id: str, context: str = None):
    guild_id = interaction.guild_id
    event_data = events.get_event_by_id(guild_id, event_id)
    if not event_data:
        await interaction.response.send_message("❌ Event not found.", ephemeral=True)
        return

    if not event_data.availability:
        if context == "bulletin":
            await interaction.response.send_message(f"📅 No time slots have been proposed for **{event_data.event_name}** yet.", ephemeral=True)
            return
        else:
            await utils.safe_send(interaction, f"📅 No time slots have been proposed for **{event_data.event_name}** yet.")
            return
    user_tz_str = userdata.get_user_timezone(interaction.user.id)
    if not user_tz_str:
        if context == "bulletin":
            await interaction.response.send_message(
                "❌ Please set your timezone using `/settimezone` first!",
                view=timezone.RegionSelectView(interaction.user.id),
                ephemeral=True
            )
        else:
            await utils.safe_send(
                interaction,
                "❌ Please set your timezone using `/settimezone` first!",
                view=timezone.RegionSelectView(interaction.user.id)
            )    
    
    if event_data.confirmed_dates:
        confirmed_availability = { f"{iso_str}" : event_data.availability.get(f"{iso_str}", {}) for iso_str in event_data.confirmed_dates}
        local_slots_by_date = utils.from_utc_to_local(confirmed_availability, user_tz_str)

    else:
        local_slots_by_date = utils.from_utc_to_local(event_data.availability, user_tz_str)

    if not local_slots_by_date:
        if context == "bulletin":
            await interaction.response.send_message(
                f"📅 No time slots available for **{event_data.event_name}**.",
                ephemeral=True
            )
            return
        else:
            await utils.safe_send(
                interaction,
                f"📅 No time slots available for **{event_data.event_name}**."
            )
            return
    view = PaginatedHourSelectionView(event_data, local_slots_by_date, int(interaction.user.id), context)
    try:
        if interaction.type.name == "component" and not context == "bulletin":
            await interaction.response.edit_message(content=view.render_date_label(), view=view)
        else:
            await interaction.response.send_message(content=view.render_date_label(), view=view, ephemeral=True)
        await view.wait()
        
        if not view.submit:
            await interaction.edit_original_response(
                content=f"✅ No selection changes for **{event_data.event_name}**.\n\n **Thanks for wasting electricity* 🫠",
                view=None
            )
            return
        
        selected_dates = view.selected_utc_keys.copy()
        selected_utc_iso_strs = [iso_str for iso_str, _, _ in selected_dates]
        for utc_iso_str in selected_utc_iso_strs:
            user_list = event_data.availability.get(utc_iso_str, {})
            if interaction.user.id not in user_list.values():
                next_position = str(len(user_list) + 1) 
                event_data.availability[utc_iso_str][next_position] = interaction.user.id
                changed = True
        
        for utc_iso_str, user_dict in event_data.availability.items():
            user_list = event_data.availability.get(utc_iso_str, {})
            if utc_iso_str not in selected_utc_iso_strs and interaction.user.id in user_list.values():
                updated_queue = events.remove_user_from_queue(user_dict, interaction.user.id)
                event_data.availability[utc_iso_str] = updated_queue
                changed = True

        if events.user_has_any_availability(interaction.user.id, event_data.availability):
            event_data.rsvp.append(interaction.user.id)
        else:
            event_data.rsvp.remove(interaction.user.id)

        if changed:
            events.modify_event(event_data)
            # Get message info for this slot
            event_msg_directory = bulletins.get_event_bulletin(guild_id=event_data.guild_id)
            if not event_data.bulletin_message_id:
                await interaction.edit_original_response(
                    content=f"✅ Availability updated for **{event_data.event_name}**.",
                    view=None
                )
                return
            elif not event_msg_directory.get(f"{event_data.bulletin_message_id}",False):
                print(f"[Submit_Registration][{event_data.event_name}:{event_data.event_id}]ERROR: Bulletin id set, but unable to be located.")
                await interaction.response.edit_message(
                    content=f"✅ Availability updated for **{event_data.event_name}**.",
                    view=None
                )
                return
            ###### THREADS GO HERE ######
            # Update main bulletin head message
            await bulletins.update_bulletin_header(interaction.client, event_data)
            await interaction.edit_original_response(
                content=f"✅ Availability updated for **{event_data.event_name}**.",
                view=None
            ) 
        else:
            await interaction.edit_original_response(
                content=f"✅ No selection changes for **{event_data.event_name}**.\n\n **Thanks for wasting electricity* 🫠",
                view=None
            )
    except discord.HTTPException as e:
        await interaction.followup.send(f"❌ Failed to display schedule view: {str(e)}", ephemeral=True)    

class PaginatedHourSelectionView(View):
    def __init__(self, event, slots_data_by_date, user_id, context="register"):
        super().__init__(timeout=900)
        self.event = event
        self.user_id = user_id
        self.context = context
        self.page = 0
        self.current_date_index = 0
        self.selected_utc_keys = set()
        self.submit = False

        self.date_objs = []
        self.slots_by_date = []

        for date_label, slots in slots_data_by_date:
            processed_slots = []
            for local_dt, utc_iso_str, users in slots:
                date_key = local_dt.strftime("%A, %m/%d/%y")
                hour_key = local_dt.strftime("%-I %p")
                processed_slots.append((utc_iso_str, local_dt, date_key, hour_key, users))

                if context != "confirm" and user_id in users.values():
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
        page_slots = slots[start:end]

        # Add exactly 12 slot buttons across 3 rows of 4
        for i in range(MAX_TIME_BUTTONS):
            row = i // 4
            if i < len(page_slots):
                utc_iso_str, local_dt, date_key, hour_key, users = page_slots[i]
                selected = (utc_iso_str, date_key, hour_key) in self.selected_utc_keys
                count = len(users)
                button = LocalizedHourToggleButton(
                    utc_iso_str, local_dt, date_key, hour_key, selected, count
                )
            else:
                button = DisabledPaddingButton()

            button.row = row  # Force slot buttons into row 0, 1, 2
            self.add_item(button)

        total_pages = (len(slots) - 1) // MAX_TIME_BUTTONS

        # Row 4: Navigation
        self.add_item(NavButton("⏪ Prev Date", "prev_date", disabled=self.current_date_index == 0))
        self.add_item(NavButton("◀️ Earlier Times", "earlier", disabled=self.page == 0))
        self.add_item(NavButton("Later Times ▶️", "later", disabled=self.page >= total_pages))
        self.add_item(NavButton("Next Date ⏩", "next_date", disabled=self.current_date_index >= len(self.date_objs) - 1))

        # Row 5: Select / Submit / Cancel
        self.add_item(SelectAllButton("Select All on Page"))
        self.add_item(SubmitAllButton(context=self.context))
        self.add_item(CancelButton("Cancel"))

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
    def __init__(self, context="register"):
        super().__init__(label="✅ Submit Times", style=ButtonStyle.primary, row=4)
        self.context = context

    async def callback(self, interaction):
        view: PaginatedHourSelectionView = self.view
        eid= view.event.event_id
        event_data = events.get_event_by_id(interaction.guild.id,eid)
        confirmed_utc = [utc for (utc, _, _) in view.selected_utc_keys]
        view.submit = True

        if self.context == "confirm":
            # Store final confirmed times
            event_data.confirmed_dates = confirmed_utc
            events.modify_event(event_data)
            event_msg_directory = bulletins.get_event_bulletin(guild_id=event_data.guild_id)
            if not event_data.bulletin_message_id:
                await interaction.response.edit_message(
                    content=f"✅ Availability updated for **{event_data.event_name}**.",
                    view=None
                )
                return
            elif not event_msg_directory.get(f"{event_data.bulletin_message_id}",False):
                print(f"[Submit_Registration][{event_data.event_name}:{event_data.event_id}]ERROR: Bulletin id set, but unable to be located.")
                await interaction.response.edit_message(
                    content=f"✅ Availability updated for **{event_data.event_name}**.",
                    view=None
                )
                return
            ###### THREADS GO HERE ######
            # Update main bulletin head message
            await bulletins.update_bulletin_header(interaction.client, event_data)
            await interaction.response.edit_message(content=f"✅ Dates confirmed for {event_data.event_name}", view=None)
        
        view.stop()

class NavButton(Button):
    def __init__(self, label, action, disabled=False):
        super().__init__(label=label, style=ButtonStyle.secondary, row=3, custom_id=f"nav_{action}", disabled=disabled)

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

class DisabledPaddingButton(Button):
    def __init__(self):
        super().__init__(label="\u200b", style=discord.ButtonStyle.secondary, disabled=True)
        
class SelectAllButton(Button):
    def __init__(self, label="Select All on Page", row=4):
        super().__init__(label=label, style=discord.ButtonStyle.secondary, row=row, custom_id="select_all")

    async def callback(self, interaction: discord.Interaction):
        view: PaginatedHourSelectionView = self.view
        slots = view.slots_by_date[view.current_date_index]
        start = view.page * MAX_TIME_BUTTONS
        end = start + MAX_TIME_BUTTONS
        page_slots = slots[start:end]

        slot_keys_on_page = {(utc, date_key, hour_key) for utc, _, date_key, hour_key, _ in page_slots}
        selected_on_page = view.selected_utc_keys & slot_keys_on_page

        if len(selected_on_page) == len(slot_keys_on_page):
            # All selected: deselect all on page
            view.selected_utc_keys -= slot_keys_on_page
        else:
            # Some or none selected: select all on page
            view.selected_utc_keys |= slot_keys_on_page

        view.render_buttons()
        await interaction.response.edit_message(content=view.render_date_label(), view=view)

class CancelButton(Button):
    def __init__(self, label="Cancel"):
        super().__init__(label=label, style=discord.ButtonStyle.danger, row=4, custom_id="cancel")

    async def callback(self, interaction: discord.Interaction):
        view: PaginatedHourSelectionView = self.view
        view.selected_utc_keys = []
        view.submit = False
        await interaction.response.edit_message(content="❌ Selection cancelled.", view=None)
        self.view.stop()
        
## Temp removed thread logic
            # event_bulletin_msg = event_msg_directory[f"{event_data.bulletin_message_id}"]
            # thread = interaction.client.get_channel(int(event_bulletin_msg.thread_id))
            # for msg, slots in event_bulletin_msg.thread_messages.items():
            #     message = await thread.fetch_message(int(msg))

            #     new_embed = bulletins.generate_single_embed_for_message(event_data, str(message.id))
            #     if new_embed:
            #         # Rebuild the view (button rows) for this embed
            #         view = bulletins.ThreadView(event_data.event_name, [
            #             (info["embed_index"], slot)
            #             for slot, info in event_data.availability_to_message_map.items()
            #             if info["message_id"] == str(message.id)
            #         ])
            #         await message.edit(embed=new_embed, view=view)
