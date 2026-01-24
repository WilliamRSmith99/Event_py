from dataclasses import dataclass, field
from typing import Dict, Any, Union
from core.storage import read_json, write_json_atomic
from core import events, utils, conf
from core.logging import get_logger, log_event_action
from datetime import datetime, timedelta
from commands.event import register
import discord
from discord.ui import Button, View
from core.views import GlobalBulletinView, GlobalThreadView
from core.emojis import EMOJIS_MAP

logger = get_logger(__name__)



# ========== General Bulletin Logic ==========

def format_discord_timestamp(iso_str: str) -> str:
    """Return a Discord full timestamp (<t:...:f>) from UTC ISO string."""
    dt = datetime.fromisoformat(iso_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return f"<t:{int(dt.timestamp())}:f>"

def group_consecutive_hours_timestamp(availability: dict) -> list[str]:
    """
    Groups adjacent 1-hour UTC slots from event_data.availability.
    Returns strings showing full Discord timestamps with RSVP counts.
    """
    if not availability:
        return []

    # Sort by UTC datetime
    sorted_slots = sorted(
        [(datetime.fromisoformat(ts), ts, len(users)) for ts, users in availability.items()],
        key=lambda x: x[0]
    )

    output = []
    start_dt, start_ts, max_rsvp = sorted_slots[0]
    end_dt = start_dt + timedelta(hours=1)
    end_ts = start_ts

    for i in range(1, len(sorted_slots)):
        current_dt, current_ts, rsvp_count = sorted_slots[i]
        next_end = current_dt + timedelta(hours=1)

        if current_dt <= end_dt + timedelta(minutes=5):  # allow small overlap
            end_dt = next_end
            end_ts = current_ts
            max_rsvp = max(max_rsvp, rsvp_count)
        else:
            output.append(
                f"{format_discord_timestamp(start_ts)} -> {format_discord_timestamp(end_ts)} (RSVPs: {max_rsvp})"
            )
            start_dt, start_ts, max_rsvp = current_dt, current_ts, rsvp_count
            end_dt = next_end
            end_ts = current_ts

    # Final range
    output.append(
        f"{format_discord_timestamp(start_ts)} -> {format_discord_timestamp(end_ts)} (RSVPs: {max_rsvp})"
    )

    return output

def generate_thread_messages(event_data) -> list[tuple[discord.Embed, dict[str, str]]]:
    """
    Returns a list of (embed, emoji_map) tuples.
    - Each embed shows up to 9 time slots with RSVP lists.
    - emoji_map maps emoji to UTC ISO timestamp for that embed.
    """
    all_slots = sorted(event_data.availability.keys())
    grouped_embeds = []

    for i in range(0, len(all_slots), 9):
        chunk = all_slots[i:i + 9]
        emoji_map = {}

        embed = discord.Embed(
            title=f"🗓️ Event Signup – {event_data.event_name}",
            description="React to register for a slot below.",
            color=discord.Color.blue()
        )

        for j, utc_iso in enumerate(chunk):
            emoji = EMOJIS_MAP.get(f"{j}", "⚠️ 404")
            emoji_map[j] = utc_iso
            timestamp = format_discord_timestamp(utc_iso)
            users_dict = event_data.availability.get(utc_iso, {})

            user_lines = []
            for placement, user in sorted(users_dict.items()):
                if event_data.max_attendees is not None and placement > event_data.max_attendees:
                    user_lines.append(f"⏳ <@{user}>")
                else:
                    user_lines.append(f"✅ <@{user}>")

            field_name = f"{emoji}🕓 {timestamp}"
            if not user_lines:
                field_value = "No signups yet"
            else:
                field_value = "\n".join(user_lines)
                if len(field_value) > 1024:
                    field_value = "\n".join(user_lines[:40]) + f"\n...and {len(user_lines) - 40} more"

            embed.add_field(name=field_name, value=field_value, inline=True)

        grouped_embeds.append((embed, emoji_map))

    return grouped_embeds

def generate_single_embed_for_message(event_data, message_id: str) -> discord.Embed:
    for embed, emoji_map in generate_thread_messages(event_data):
        for emoji, slot in emoji_map.items():
            msg_info = event_data.availability_to_message_map.get(slot)
            if msg_info and msg_info["message_id"] == message_id:
                return embed
    return None

async def generate_new_bulletin(interaction: discord.Interaction, event_data, server_config):
    channel = interaction.guild.get_channel(int(server_config.bulletin_channel))
    if not channel:
        logger.warning(f"Bulletin channel not found: {server_config.bulletin_channel} in guild {interaction.guild.id}")
        return  # Skip if channel is not found

    # Check if we should use threads or just a register button
    use_threads = getattr(server_config, "bulletin_use_threads", True)

    event_data.bulletin_channel_id = str(server_config.bulletin_channel)
    proposed_dates = "\n".join(f"• {d}" for d in group_consecutive_hours_timestamp(event_data.availability))

    if use_threads:
        # Full bulletin with thread for time slot selection
        # No register button when threads are enabled - users register in the thread
        bulletin_body = (
            f"📅 **Event:** `{event_data.event_name}`\n"
            f"🙋 **Organizer:** <@{event_data.organizer}>\n"
            f"✅ **Confirmed Date:** *{event_data.confirmed_date or 'TBD'}*\n"
            f"🗓️ **Proposed Dates:**\n{proposed_dates or '*None yet*'}\n\n\n"
            "      ⬇️ Select times in the thread below!"
        )
        bulletin_view = GlobalBulletinView()
        bulletin_msg = await channel.send(content=bulletin_body, view=bulletin_view)
        event_data.bulletin_message_id = str(bulletin_msg.id)

        thread_messages = generate_thread_messages(event_data)

        thread = await bulletin_msg.create_thread(
            name=f"🧵 {event_data.event_name} Signups",
            auto_archive_duration=60,
            reason="Auto-thread for public event"
        )
        event_data.bulletin_thread_id = thread.id
        slots_to_msg = {}

        for embed, map in thread_messages:
            slot_list = [(emoji, slot) for emoji, slot in map.items()]
            view = GlobalThreadView(event_data.event_name, slot_list)
            thread_msg = await thread.send(embed=embed, view=view)

            slots_to_msg.update({
                f"{slot}": {"thread_id": f"{thread.id}", "message_id": f"{thread_msg.id}", "embed_index": f"{emoji}"}
                for emoji, slot in map.items()
            })

        event_data.availability_to_message_map = slots_to_msg
        events.modify_event(event_data)

        await interaction.response.edit_message(
            content=f"✅ **Finished setting up available times for {event_data.event_name}!**\nPosted bulletin and created signup thread in <#{server_config.bulletin_channel}>.",
            view=None
        )
    else:
        # Simple bulletin with just a register button (no threads)
        bulletin_body = (
            f"📅 **Event:** `{event_data.event_name}`\n"
            f"🙋 **Organizer:** <@{event_data.organizer}>\n"
            f"✅ **Confirmed Date:** *{event_data.confirmed_date or 'TBD'}*\n"
            f"🗓️ **Proposed Dates:**\n{proposed_dates or '*None yet*'}\n\n"
            "      ⬇️ Click \"Register\" to sign up for time slots!"
        )
        bulletin_view = GlobalBulletinView()
        bulletin_msg = await channel.send(content=bulletin_body, view=bulletin_view)
        event_data.bulletin_message_id = str(bulletin_msg.id)

        events.modify_event(event_data)

        await interaction.response.edit_message(
            content=f"✅ **Finished setting up available times for {event_data.event_name}!**\nPosted bulletin in <#{server_config.bulletin_channel}>.",
            view=None
        )

async def update_bulletin_header(client: discord.Client, event_data: events.EventState):
    """Update the bulletin header message with current event data."""
    if not event_data.bulletin_channel_id or not event_data.bulletin_message_id:
        return False

    try:
        channel = client.get_channel(int(event_data.bulletin_channel_id))
        if not channel:
            logger.warning(f"Bulletin channel not found: {event_data.bulletin_channel_id}")
            return False

        head_msg = await channel.fetch_message(int(event_data.bulletin_message_id))

        # Get server config to check if threads are enabled
        server_config = conf.get_config(int(event_data.guild_id))
        use_threads = getattr(server_config, "bulletin_use_threads", True) if server_config else True

        # Format confirmed date nicely using Discord timestamp
        confirmed_display = "TBD"
        is_confirmed = event_data.confirmed_date and event_data.confirmed_date != "TBD"
        if is_confirmed:
            try:
                confirmed_dt = datetime.fromisoformat(event_data.confirmed_date)
                confirmed_display = f"<t:{int(confirmed_dt.timestamp())}:F>"
            except ValueError:
                confirmed_display = event_data.confirmed_date

        # Only show proposed dates if event is not yet confirmed
        if is_confirmed:
            # Count attendees for the confirmed slot
            confirmed_slot_data = event_data.availability.get(event_data.confirmed_date, {})
            attendee_count = len(confirmed_slot_data)
            max_display = f"/{event_data.max_attendees}" if event_data.max_attendees else ""

            # Calculate waitlist if max_attendees is set
            waitlist_line = ""
            if event_data.max_attendees:
                max_int = int(event_data.max_attendees)
                waitlist_count = sum(1 for pos in confirmed_slot_data.keys() if int(pos) > max_int)
                if waitlist_count > 0:
                    waitlist_line = f"⏳ **Waitlist:** {waitlist_count}\n"

            bulletin_body = (
                f"📅 **Event:** `{event_data.event_name}`\n"
                f"🙋 **Organizer:** <@{event_data.organizer}>\n"
                f"✅ **Confirmed Date:** {confirmed_display}\n"
                f"👥 **Registered:** {attendee_count}{max_display}\n"
                f"{waitlist_line}\n"
                "      ⬇️ Click \"Register\" to sign up!\n"
            )
            # When confirmed, always show register button (single slot to register for)
            bulletin_view = GlobalBulletinView()
        else:
            proposed_dates = "\n".join(f"• {d}" for d in group_consecutive_hours_timestamp(event_data.availability))
            if use_threads:
                bulletin_body = (
                    f"📅 **Event:** `{event_data.event_name}`\n"
                    f"🙋 **Organizer:** <@{event_data.organizer}>\n"
                    f"✅ **Confirmed Date:** *{confirmed_display}*\n"
                    f"🗓️ **Proposed Dates:**\n{proposed_dates or '*None yet*'}\n\n\n"
                    "      ⬇️ Select times in the thread below!\n"
                )
                bulletin_view = GlobalBulletinView()
            else:
                bulletin_body = (
                    f"📅 **Event:** `{event_data.event_name}`\n"
                    f"🙋 **Organizer:** <@{event_data.organizer}>\n"
                    f"✅ **Confirmed Date:** *{confirmed_display}*\n"
                    f"🗓️ **Proposed Dates:**\n{proposed_dates or '*None yet*'}\n\n\n"
                    "      ⬇️ Click \"Register\" to sign up for time slots!\n"
                )
                bulletin_view = GlobalBulletinView()

        await head_msg.edit(content=bulletin_body, view=bulletin_view)
        logger.info(f"Updated bulletin header for '{event_data.event_name}'")
        return True

    except discord.NotFound:
        logger.warning(f"Bulletin message not found: {event_data.bulletin_message_id}")
        return False
    except Exception as e:
        logger.error(f"Failed to update bulletin header: {e}")
        return False


async def delete_bulletin_message(client: discord.Client, event_data: events.EventState) -> bool:
    """
    Delete the bulletin message and thread for an event.
    Args:
        client: Discord client
        event_data: The event whose bulletin should be deleted
    Returns:
        True if deleted successfully
    """
    if not event_data.bulletin_channel_id or not event_data.bulletin_message_id:
        return False

    try:
        channel = client.get_channel(int(event_data.bulletin_channel_id))
        if not channel:
            logger.warning(f"Bulletin channel not found: {event_data.bulletin_channel_id}")
            return False

        head_msg = await channel.fetch_message(int(event_data.bulletin_message_id))

        # Delete the message (this also deletes the thread)
        await head_msg.delete()

        logger.info(f"Deleted bulletin for '{event_data.event_name}'")
        return True

    except discord.NotFound:
        # Message already deleted
        return True
    except Exception as e:
        logger.error(f"Failed to delete bulletin: {e}")
        return False
    

async def handle_slot_selection(interaction: discord.Interaction, selected_slot: str, event_name: str):
    user_id = str(interaction.user.id)
    user_display = interaction.user.display_name

    # Load events and find event
    event_data = events.get_events(interaction.guild.id,event_name)
    if not event_data:
        return await interaction.response.send_message("Event not found.", ephemeral=True)

    # Register or unregister user
    slot_availability = event_data[event_name].availability.setdefault(selected_slot, {})
    if user_id not in slot_availability.values():
        next_position = str(len(slot_availability) + 1)
        event_data[event_name].availability[selected_slot][next_position] = user_id
        action = "✅ Registered"
    else:
        updated_queue = events.remove_user_from_queue(slot_availability, user_id)
        event_data[event_name].availability[selected_slot] = updated_queue
        action = "❌ Unregistered"

    events.modify_event(event_data[event_name])


    # Get message info for this slot
    slot_msg_info = event_data[event_name].availability_to_message_map.get(selected_slot)
    if not slot_msg_info:
        return await interaction.response.send_message("Failed to locate slot message.", ephemeral=True)

    thread = interaction.client.get_channel(int(slot_msg_info["thread_id"]))
    message = await thread.fetch_message(int(slot_msg_info["message_id"]))

    # Rebuild embed
    new_embed = generate_single_embed_for_message(event_data[event_name], str(message.id))
    if new_embed:
        # Rebuild the view (button rows) for this embed
        view = GlobalThreadView()
        await message.edit(embed=new_embed, view=view)

    # Update main bulletin head message
    await update_bulletin_header(interaction.client, event_data[event_name])

    # Save updated events
    events.modify_event(event_data[event_name])

async def mark_bulletin_as_past(client: discord.Client, event_data: events.EventState) -> bool:
    """
    Update a bulletin to show the event has ended.
    Removes interactive buttons and updates the message to indicate
    the event is now in the past.
    Args:
        client: Discord client
        event_data: The event that has ended
    Returns:
        True if updated successfully
    """
    if not event_data.bulletin_channel_id or not event_data.bulletin_message_id:
        return False

    try:
        channel = client.get_channel(int(event_data.bulletin_channel_id))
        if not channel:
            logger.warning(f"Bulletin channel not found: {event_data.bulletin_channel_id}")
            return False

        head_msg = await channel.fetch_message(int(event_data.bulletin_message_id))

        # Format confirmed date nicely
        confirmed_display = "TBD"
        if event_data.confirmed_date and event_data.confirmed_date != "TBD":
            try:
                confirmed_dt = datetime.fromisoformat(event_data.confirmed_date)
                confirmed_display = f"<t:{int(confirmed_dt.timestamp())}:F>"
            except ValueError:
                confirmed_display = event_data.confirmed_date

        # Create "event ended" bulletin body
        bulletin_body = (
            f"📅 **Event:** `{event_data.event_name}`\n"
            f"🙋 **Organizer:** <@{event_data.organizer}>\n"
            f"✅ **Date:** {confirmed_display}\n\n"
            f"✨ **This event has ended.**\n\n"
            f"*Thank you to everyone who participated!*"
        )

        # Remove view (disables buttons)
        await head_msg.edit(content=bulletin_body, view=None)

        logger.info(f"Marked bulletin for '{event_data.event_name}' as past")
        return True

    except discord.NotFound:
        logger.warning(f"Bulletin message not found: {event_data.bulletin_message_id}")
        return False
    except Exception as e:
        logger.error(f"Failed to mark bulletin as past: {e}")
        return False


async def update_past_event_bulletins(client: discord.Client, guild_id: int) -> int:
    """
    Update all bulletins for past events in a guild.
    Args:
        client: Discord client
        guild_id: Guild ID
    Returns:
        Number of bulletins updated
    """
    past_events = events.get_past_events(guild_id)
    updated_count = 0

    for event in past_events:
        if await mark_bulletin_as_past(client, event):
            updated_count += 1

    if updated_count > 0:
        logger.info(f"Updated {updated_count} past event bulletins for guild {guild_id}")

    return updated_count