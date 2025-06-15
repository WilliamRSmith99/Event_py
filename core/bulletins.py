from dataclasses import dataclass, field
from typing import Dict, Any, Union
from core.storage import read_json, write_json_atomic
from core import events,utils,userdata,auth
from datetime import datetime, timedelta
from commands.event import register,responses, manage, lists
from commands.user import timezone
import discord
from discord.ui import Button, View



EMOJIS_MAP = {"0":'1️⃣',"1":'2️⃣',"2":'3️⃣',"3":'4️⃣',"4":'5️⃣',"5":'6️⃣',"6":'7️⃣',"7":'8️⃣',"8":'9️⃣'}
EVENT_BULLETIN_FILE_NAME = "event_bulletin.json"

# ========== Data Model ==========

@dataclass
class BulletinMessageEntry:
    event: str = ""
    event_id: str = ""
    msg_head_id: str = ""
    guild_id: str = ""
    channel_id: str = ""
    thread_id: str = ""
    thread_messages: Dict[str, Dict[str, str]] = field(default_factory=dict)
    # Structure: {THREAD_MSG_ID: {"options": {emoji: value}}}

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "BulletinMessageEntry":
        return BulletinMessageEntry(
            event=data.get("event", ""),
            event_id=data.get("event_id", ""),
            msg_head_id=data.get("msg_head_id", ""),
            guild_id=data.get("guild_id", ""),
            channel_id=data.get("channel_id", ""),
            thread_id=data.get("thread_id", ""),
            thread_messages=data.get("thread_messages", {})
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event": self.event,
            "event_id": self.event_id,
            "msg_head_id": self.msg_head_id,
            "thread_id": self.thread_id,
            "guild_id": self.guild_id,
            "channel_id": self.channel_id,
            "thread_messages": self.thread_messages
        }

# ========== In-Memory Store ==========

def load_event_bulletins() -> Dict[str, Dict[str, BulletinMessageEntry]]:
    try:
        raw = read_json(EVENT_BULLETIN_FILE_NAME)
        return {
            guild_id: {
                head_msg_id: BulletinMessageEntry.from_dict(head_data)
                for head_msg_id, head_data in guild_data.items()
            }
            for guild_id, guild_data in raw.items()
        }
    except FileNotFoundError:
        return {}

# ========== Save ==========

def save_event_bulletins(data: Dict[str, Dict[str, BulletinMessageEntry]]) -> None:
    to_save = {
        guild_id: {
            head_msg_id: entry.to_dict()
            for head_msg_id, entry in head_msgs.items()
        }
        for guild_id, head_msgs in data.items()
    }
    write_json_atomic(EVENT_BULLETIN_FILE_NAME, to_save)

# ========== CRUD ==========

def get_event_bulletin(guild_id: Union[str, int]) -> Dict[str, BulletinMessageEntry]:
    event_bulletins = load_event_bulletins()
    gid = str(guild_id)
    if gid not in event_bulletins:
        event_bulletins[gid] = {}
        save_event_bulletins(event_bulletins)
    return event_bulletins[gid]

def modify_event_bulletin(guild_id: Union[str, int], entry: BulletinMessageEntry) -> None:
    head_msg_id = entry.msg_head_id
    event_bulletins = load_event_bulletins()
    gid = str(guild_id)
    if gid not in event_bulletins:
        event_bulletins[gid] = {}
    event_bulletins[gid][head_msg_id] = entry
    save_event_bulletins(event_bulletins)

def delete_event_bulletin(guild_id: Union[str, int], head_msg_id: str) -> bool:
    event_bulletins = load_event_bulletins()
    gid = str(guild_id)
    try:
        del event_bulletins[gid][head_msg_id]
        if not event_bulletins[gid]:
            del event_bulletins[gid]
        save_event_bulletins(event_bulletins)
        return True
    except KeyError:
        return False

# ========== General Bulletin Logic ==========

async def restore_bulletin_views(client: discord.Client):
    all_bulletins = load_event_bulletins()
    msg_count = 0
    for guild_id, bulletin_map in all_bulletins.items():
        for head_msg_id, bulletin in bulletin_map.items():
            try:
                event = events.get_event_by_id(guild_id,bulletin.event_id)
                view = lists.EventView(event, "bulletin", False)
                view.add_item(lists.ManageEventButton(event, "bulletin"))
                client.add_view(view, message_id=int(head_msg_id))
                msg_count+=1
                ###### THREADING GOES HERE #####
    
            except Exception as e:
                print(f"⚠️ Failed to restore view for bulletin '{bulletin.event}' in guild {guild_id}: {e}")
    print(f"Loaded {msg_count} bulletins from disk.")

async def update_bulletin_header(client: discord.Client, event_data: events.EventState):
    bulletin = client.get_channel(int(event_data.bulletin_channel_id))
    head_msg = await bulletin.fetch_message(int(event_data.bulletin_message_id))
    event_data = events.get_event_by_id(event_data.guild_id, event_data.event_id)
    confirmed_dates = None
    if event_data.confirmed_dates:
        confirmed_availability = { f"{iso_str}" : event_data.availability.get(f"{iso_str}", {}) for iso_str in event_data.confirmed_dates}    
        confirmed_dates = "\n".join(f"• {d}" for d in lists.group_consecutive_hours_timestamp(confirmed_availability))
    proposed_dates = "\n".join(f"• {d}" for d in lists.group_consecutive_hours_timestamp(event_data.availability))
    bulletin_body = (
        f"📅 **Event:** `{event_data.event_name}`\n"
        f"🙋 **Organizer:** <@{event_data.organizer}>\n"
        f"✅ **Confirmed Dates:** *{confirmed_dates or 'TBD'}*\n"
        f"🗓️ **Proposed Dates (*Your local time*):**\n{proposed_dates or '*None yet*'}\n\n\n"
    )
    bulletin_view=lists.EventView(event_data, "bulletin", False)
    bulletin_view.add_item(lists.ManageEventButton(event_data, "bulletin"))

    await head_msg.edit(content=bulletin_body,view=bulletin_view)
    
# ## Temporarily removed logic for threads
#### Generate new bulletin()

    # thread_messages = generate_thread_messages(event_data)
    
    # thread = await bulletin_msg.create_thread(
    #     name=f"🧵 {event_data.event_name} Signups",
    #     auto_archive_duration=60,
    #     reason="Auto-thread for public event"
    # )
    # bulletin.thread_id = thread.id
    # slots_to_msg = {}
    # for embed, map in thread_messages:
    #     slot_list = [(emoji, slot) for emoji, slot in map.items()]            
    #     view = ThreadView(event_data.event_name, slot_list)
    #     thread_msg = await thread.send(embed=embed, view=view)
    #     bulletin.thread_messages[thread_msg.id] = map

    #     slots_to_msg.update({f"{slot}":{"thread_id": f"{thread.id}", "message_id": f"{thread_msg.id}", "embed_index": f"{emoji}"} for emoji, slot in map.items()})
    
    # event_data.availability_to_message_map =  slots_to_msg    

#### Restore_Bulletin_view
                # For each thread message, get the emoji -> slot map
                # for message_id, emoji_to_slot in bulletin.thread_messages.items():
                #     slot_list = [(emoji, slot) for emoji, slot in emoji_to_slot.items()]

                #     # Create the ThreadView again
                #     view = ThreadView(bulletin.event, slot_list)

                #     # Add view back to the client
                #     client.add_view(view, message_id=int(message_id))
                #     msg_count+=1

# def generate_thread_messages(event_data) -> list[tuple[discord.Embed, dict[str, str]]]:
#     """
#     Returns a list of (embed, emoji_map) tuples.
#     - Each embed shows up to 9 time slots with RSVP lists.
#     - emoji_map maps emoji to UTC ISO timestamp for that embed.
#     """
#     all_slots = sorted(event_data.availability.keys())
#     grouped_embeds = []

#     for i in range(0, len(all_slots), 9):
#         chunk = all_slots[i:i + 9]
#         emoji_map = {}

#         embed = discord.Embed(
#             title=f"🗓️ Event Signup – {event_data.event_name}",
#             description="React to register for a slot below.",
#             color=discord.Color.blue()
#         )

#         for j, utc_iso in enumerate(chunk):
#             emoji = EMOJIS_MAP.get(f"{j}", "⚠️ 404")
#             emoji_map[j] = utc_iso
#             timestamp = format_discord_timestamp(utc_iso)
#             users_dict = event_data.availability.get(utc_iso, {})

#             user_lines = []
#             for placement, user in sorted(users_dict.items()):
#                 if event_data.max_attendees is not None and placement > event_data.max_attendees:
#                     user_lines.append(f"⏳ <@{user}>")
#                 else:
#                     user_lines.append(f"✅ <@{user}>")

#             field_name = f"{emoji}🕓 {timestamp}"
#             if not user_lines:
#                 field_value = "No signups yet"
#             else:
#                 field_value = "\n".join(user_lines)
#                 if len(field_value) > 1024:
#                     field_value = "\n".join(user_lines[:40]) + f"\n...and {len(user_lines) - 40} more"

#             embed.add_field(name=field_name, value=field_value, inline=True)

#         grouped_embeds.append((embed, emoji_map))

#     return grouped_embeds

# def generate_single_embed_for_message(event_data, message_id: str) -> discord.Embed:
#     for embed, emoji_map in generate_thread_messages(event_data):
#         for emoji, slot in emoji_map.items():
#             msg_info = event_data.availability_to_message_map.get(slot)
#             if msg_info and msg_info["message_id"] == message_id:
#                 return embed
#     return None

# async def handle_slot_selection(interaction: discord.Interaction, selected_slot: str, event_name: str):
#     user_id = str(interaction.user.id)
#     user_display = interaction.user.display_name

#     # Load events and find event
#     event_data = events.get_events_by_name(interaction.guild.id,event_name)
#     if not event_data:
#         return await interaction.response.send_message("Event not found.", ephemeral=True)

#     # Register or unregister user
#     slot_availability = event_data[event_name].availability.setdefault(selected_slot, {})
#     if user_id not in slot_availability.values():
#         next_position = str(len(slot_availability) + 1)
#         event_data[event_name].availability[selected_slot][next_position] = user_id
#         action = "✅ Registered"
#     else:
#         updated_queue = events.remove_user_from_queue(slot_availability, user_id)
#         event_data[event_name].availability[selected_slot] = updated_queue
#         action = "❌ Unregistered"

#     events.modify_event(event_data[event_name])


#     # Get message info for this slot
#     slot_msg_info = event_data[event_name].availability_to_message_map.get(selected_slot)
#     if not slot_msg_info:
#         return await interaction.response.send_message("Failed to locate slot message.", ephemeral=True)

#     thread = interaction.client.get_channel(int(slot_msg_info["thread_id"]))
#     message = await thread.fetch_message(int(slot_msg_info["message_id"]))

#     # Rebuild embed
#     new_embed = generate_single_embed_for_message(event_data[event_name], str(message.id))
#     if new_embed:
#         # Rebuild the view (button rows) for this embed
#         view = ThreadView(event_data[event_name].event_name, [
#             (info["embed_index"], slot)
#             for slot, info in event_data[event_name].availability_to_message_map.items()
#             if info["message_id"] == str(message.id)
#         ])
#         await message.edit(embed=new_embed, view=view)

#     # Update main bulletin head message
#     await update_bulletin_header(interaction.client, event_data[event_name])

#     # Save updated events
#     events.modify_event(event_data[event_name])

# class RegisterSlotButton(Button):
#     def __init__(self, event_name, slot_time: str, emoji_index: str):

#         self.event_name = event_name
#         self.slot_time = slot_time
#         self.emoji_index = emoji_index
#         self.emoji_icon = EMOJIS_MAP.get(str(emoji_index), "⚠️ 404")
#         button_label = f"{self.emoji_icon}"
#         button_style = discord.ButtonStyle.primary
#         custom_id = f"register:{self.event_name}:{slot_time}"
#         super().__init__(label=button_label, style=button_style, custom_id=custom_id)

#     async def callback(self, interaction: discord.Interaction):
#         # Access event + slot info
#         event_name, slot_time = self.event_name, self.slot_time

#         await interaction.response.defer(ephemeral=True)

#         # Register the user for this slot
#         await handle_slot_selection(
#             interaction=interaction,
#             event_name=event_name,
#             selected_slot=slot_time
#         )


# class ThreadView(View):
#     def __init__(self, event_name, slots: list[tuple[str, str]]):
#         """
#         :param event_name: Event identifier
#         :param slots: List of (emoji, slot_time) tuples
#         :param selected_slot: Optional string of current selected slot   custom_id=f"{event_name}:thread:{slots[0][1]}"
#         """
#         self.event_name = event_name
#         super().__init__(timeout=None)

#         for emoji, slot in slots:
#             self.add_item(RegisterSlotButton(event_name, slot, emoji))
