# from database import events, shared, user_data
# from commands.timezone import timezone 
# import discord
# from datetime import datetime, date 
# from discord.ui import Button, View
# from discord import ButtonStyle
# import pytz 
# from collections import defaultdict 
# from database.events import parse_utc_availability_key


# async def schedule_command(interaction: discord.Interaction, event_name: str):
#     guild_id = str(interaction.guild_id)
#     full_event_name = events.resolve_event_name(guild_id, event_name)
#     if not full_event_name:
#         await shared.safe_respond(interaction, "❌ Event not found.", ephemeral=True)
#         return

#     event = events.get_event(guild_id, full_event_name)
#     if not event:
#         await shared.safe_respond(interaction, "⚠️ Event data missing.", ephemeral=True)
#         return

#     # --- Get User Timezone ---
#     user_tz_str = user_data.get_user_timezone(interaction.user.id)
#     if not user_tz_str:
#         await shared.safe_respond(
#             interaction,
#             "❌ Please set your timezone using `/settimezone` first!",
#             ephemeral=True,
#             view=timezone.RegionSelectView(interaction.user.id) # Offer to set it
#         )
#         return
#     try:
#         user_tz = pytz.timezone(user_tz_str)
#     except pytz.UnknownTimeZoneError:
#         await shared.safe_respond(interaction, f"❌ Invalid timezone stored: {user_tz_str}. Please reset it using `/settimezone`.", ephemeral=True)
#         return

#     # --- Consolidate and Localize Available Slots ---
#     # Structure: { local_date: [ (local_dt, utc_date_key, utc_hour_key) ] }
#     local_slots_by_date = defaultdict(list)

#     if not event.availability:
#          await shared.safe_respond(interaction, f"📅 No time slots have been proposed for **{event.event_name}** yet.", ephemeral=True)
#          return

#     for utc_date_key, hours_dict in event.availability.items():
#         for utc_hour_key in hours_dict: # We only care about *available* slots, not who registered
#             utc_dt = parse_utc_availability_key(utc_date_key, utc_hour_key)
#             if utc_dt:
#                 local_dt = utc_dt.astimezone(user_tz)
#                 local_date_obj = local_dt.date()
#                 # Store the local datetime, original UTC date key, and original UTC hour key
#                 local_slots_by_date[local_date_obj].append((local_dt, utc_date_key, utc_hour_key))

#     if not local_slots_by_date:
#         await shared.safe_respond(interaction, f"📅 No time slots have been proposed for **{event.event_name}** yet.", ephemeral=True)
#         return

#     # --- Sort Local Dates and Prepare Views ---
#     sorted_local_dates = sorted(local_slots_by_date.keys())

#     await shared.safe_respond(interaction, f"🗓️ Select your availability for **{event.event_name}** (Times shown in your timezone: `{user_tz_str}`):", ephemeral=True) # Initial message

#     # --- Create and Send Views for Each Local Date ---
#     for local_date_obj in sorted_local_dates:
#         slots_for_date = sorted(local_slots_by_date[local_date_obj], key=lambda x: x[0]) # Sort slots by local time
#         # You'll need a new View class designed for this
#         view = LocalizedHourSelectionView(
#             event=event,
#             local_date_obj=local_date_obj,
#             slots_data=slots_for_date, # List of (local_dt, utc_date_key, utc_hour_key)
#             user_id=str(interaction.user.id)
#         )
#         # Format the date nicely for the message content
#         local_date_str = local_date_obj.strftime("%A, %B %d, %Y")
#         # Use followup for subsequent messages if the first response was just text
#         await interaction.followup.send(
#              f"📅 **{local_date_str} (Your Time)**",
#              view=view,
#              ephemeral=True
#         )
        
# def user_has_any_availability(user_id: str, availability: dict) -> bool:
#     for date_slots in availability.values():
#         for user_list in date_slots.values():
#             if user_id in user_list:
#                 return True
#     return False
       
# class LocalizedHourToggleButton(discord.ui.Button):
#     def __init__(self, local_dt: datetime, utc_date_key: str, utc_hour_key: str, is_selected: bool, attendee_count: int):
#         self.local_dt = local_dt
#         self.utc_date_key = utc_date_key
#         self.utc_hour_key = utc_hour_key

#         # Format label using local time, e.g., "09:00 AM" or "11:30 PM"
#         hour_label = local_dt.strftime("%I:%M %p").lstrip("0")
#         if attendee_count == 0:
#             label = f"{hour_label}"
#         else:
#             label = f"{hour_label}  [👥 {attendee_count}]"
            
#         super().__init__(
#             label=label,
#             style=discord.ButtonStyle.success if is_selected else discord.ButtonStyle.secondary,
#             custom_id=f"toggle_{utc_date_key}_{utc_hour_key}" 
#         )

#     async def callback(self, interaction: discord.Interaction):
#         # Get the parent view
#         view: LocalizedHourSelectionView = self.view

#         utc_key_tuple = (self.utc_date_key, self.utc_hour_key)

#         # Toggle selection state in the parent view
#         if utc_key_tuple in view.selected_utc_keys:
#             view.selected_utc_keys.remove(utc_key_tuple)
#             self.style = discord.ButtonStyle.secondary
#         else:
#             view.selected_utc_keys.add(utc_key_tuple)
#             self.style = discord.ButtonStyle.success

#         # Edit the message to reflect the button style change
#         await interaction.response.edit_message(view=view)


# class SubmitLocalizedButton(discord.ui.Button):
#     def __init__(self):
#         super().__init__(label="✅ Submit for this Date", style=discord.ButtonStyle.primary, row=4)

#     async def callback(self, interaction: discord.Interaction):
#         view: LocalizedHourSelectionView = self.view
#         user_id = view.user_id
#         event = view.event

#         presented_utc_keys = {(slot_data[1], slot_data[2]) for slot_data in view.slots_data}
#         changed = False

#         for utc_date_key, utc_hour_key in presented_utc_keys:
#             if utc_date_key not in event.availability: continue
#             if utc_hour_key not in event.availability[utc_date_key]: continue

#             current_users = event.availability[utc_date_key][utc_hour_key]

#             if (utc_date_key, utc_hour_key) in view.selected_utc_keys:
#                 if user_id not in current_users:
#                     event.availability[utc_date_key][utc_hour_key].add(user_id)
#                     changed = True
#             else:
#                 if user_id in event.availability[utc_date_key][utc_hour_key]:
#                     event.availability[utc_date_key][utc_hour_key].remove(user_id)
#                     changed = True

#         # --- Recheck RSVP status globally ---
#         if user_has_any_availability(user_id, event.availability):
#             if user_id not in event.rsvp:
#                 event.rsvp.add(user_id)
#                 changed = True
#         else:
#             try:
#                 event.rsvp.remove(user_id)
#                 changed = True
#             except ValueError:
#                 pass


#         if changed:
#             events.modify_event(event)

#         local_date_str = view.local_date_obj.strftime("%A, %B %d")
#         await interaction.response.edit_message(
#             content=f"✅ Availability updated for **{local_date_str}** on event **{event.event_name}**.",
#             view=None
#         )
#         view.stop()

# class LocalizedHourSelectionView(discord.ui.View):
#     def __init__(self, event: events.EventState, local_date_obj: date, slots_data: list, user_id: str):
#         super().__init__(timeout=900) # 15 minutes timeout
#         self.event = event
#         self.local_date_obj = local_date_obj
#         self.slots_data = slots_data # List of (local_dt, utc_date_key, utc_hour_key)
#         self.user_id = user_id

#         # --- Determine initially selected slots for *this user* ---
#         self.selected_utc_keys = set()
#         for local_dt, utc_date_key, utc_hour_key in self.slots_data:
#              # Check if user is already registered for this specific UTC slot
#              if user_id in event.availability.get(utc_date_key, {}).get(utc_hour_key, []):
#                  self.selected_utc_keys.add((utc_date_key, utc_hour_key))

#         # --- Create Buttons ---
#         # Group buttons potentially by AM/PM or in rows for clarity if many slots
#         for slot_local_dt, slot_utc_date_key, slot_utc_hour_key in self.slots_data:
#              is_selected = (slot_utc_date_key, slot_utc_hour_key) in self.selected_utc_keys
#              num_attendees = len(event.availability.get(slot_utc_date_key, {}).get(slot_utc_hour_key, []))
#              print(len(event.availability.get(slot_utc_date_key, {}).get(slot_utc_hour_key, [])))#f"{slot_utc_hour_key}: num_attendees - {num_attendees}")
#              button = LocalizedHourToggleButton(
#                  local_dt=slot_local_dt,
#                  utc_date_key=slot_utc_date_key,
#                  utc_hour_key=slot_utc_hour_key,
#                  is_selected=is_selected,
#                  attendee_count=num_attendees
#              )
#              self.add_item(button)

#         # --- Add Submit Button ---
#         self.add_item(SubmitLocalizedButton())

#     async def on_timeout(self):
#         # Optional: Edit message on timeout to indicate expiration
#         # Needs the original interaction or message reference if editing is desired
#         pass
