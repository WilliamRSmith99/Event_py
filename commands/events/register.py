import discord, pytz
from collections import defaultdict
from core import utils, user_state, events
from ui.views import timezone, register

async def schedule_command(interaction: discord.Interaction, event_name: str):
    guild_id = interaction.guild_id
    matches = events.get_events(guild_id, event_name)

    if not matches or len(matches) != 1:
        await interaction.response.send_message("❌ Event not found.", ephemeral=True)
        return

    event = list(matches.values())[0]
    if not event or not event.availability:
        await utils.safe_respond(interaction, f"📅 No time slots have been proposed for **{event.event_name}** yet.", ephemeral=True)
        return

    user_tz_str = user_state.get_user_timezone(interaction.user.id)
    if not user_tz_str:
        await utils.safe_respond(
            interaction,
            "❌ Please set your timezone using `/settimezone` first!",
            ephemeral=True,
            view=timezone.RegionSelectView(interaction.user.id)
        )
        return

    try:
        user_tz = pytz.timezone(user_tz_str)
    except pytz.UnknownTimeZoneError:
        await utils.safe_respond(
            interaction,
            f"❌ Invalid timezone stored: {user_tz_str}. Please reset it using `/settimezone`.",
            ephemeral=True
        )
        return

    local_slots_by_date = defaultdict(list)

    for utc_date_key, hours in event.availability.items():
        for utc_hour_key in hours:
            utc_dt = utils.parse_utc_availability_key(utc_date_key, utc_hour_key)
            if utc_dt:
                local_dt = utc_dt.astimezone(user_tz)
                local_slots_by_date[local_dt.date()].append((local_dt, utc_date_key, utc_hour_key))

    if not local_slots_by_date:
        await utils.safe_respond(
            interaction,
            f"📅 No time slots available for **{event.event_name}**.",
            ephemeral=True
        )
        return

    sorted_dates = sorted(local_slots_by_date.keys())
    slots_by_date = [sorted(local_slots_by_date[d], key=lambda x: x[0]) for d in sorted_dates]
    view = register.PaginatedHourSelectionView(event, sorted_dates, slots_by_date, str(interaction.user.id))

    try:
        if interaction.type.name == "component":
            await interaction.response.edit_message(content=view.render_date_label(), view=view)
        else:
            await interaction.response.send_message(content=view.render_date_label(), view=view, ephemeral=True)
    except discord.HTTPException as e:
        await interaction.followup.send(f"❌ Failed to display schedule view: {str(e)}", ephemeral=True)

def user_has_any_availability(user_id: str, availability: dict) -> bool:
    return any(
        user_id in user_list
        for hour_map in availability.values()
        for user_list in hour_map.values()
    )
