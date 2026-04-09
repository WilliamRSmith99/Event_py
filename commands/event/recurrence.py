"""
/recurrence command — configure recurring schedule for an event (Premium feature).

Organizers call this after creating a confirmed event to set up automatic
instance generation (weekly, biweekly, monthly).
"""
import discord
from core import events, entitlements
from core.events import RecurrenceConfig, RecurrenceType
from core.entitlements import Feature
from core.logging import get_logger

logger = get_logger(__name__)

RECURRENCE_DISPLAY = {
    "weekly": "weekly",
    "biweekly": "every 2 weeks",
    "monthly": "monthly",
}

RECURRENCE_TYPE_MAP = {
    "weekly": RecurrenceType.WEEKLY,
    "biweekly": RecurrenceType.BIWEEKLY,
    "monthly": RecurrenceType.MONTHLY,
}


async def set_recurrence(
    interaction: discord.Interaction,
    event_name: str,
    recurrence_type: str,
) -> None:
    guild_id = interaction.guild_id

    # Resolve event
    matches = events.get_events(guild_id, event_name)
    if not matches:
        await interaction.response.send_message("❌ Event not found.", ephemeral=True)
        return

    event = list(matches.values())[0]

    # Permission: must be organizer or admin
    if interaction.user.id != event.organizer:
        from core.permissions import require_permission, PermissionLevel
        allowed = await require_permission(interaction, PermissionLevel.ADMIN)
        if not allowed:
            return

    # Disable path
    if recurrence_type == "none":
        event.recurrence = RecurrenceConfig(type=RecurrenceType.NONE)
        events.modify_event(event)
        await interaction.response.send_message(
            f"✅ Recurrence disabled for **{event.event_name}**.", ephemeral=True
        )
        return

    # Premium gate
    if not entitlements.has_feature(guild_id, Feature.RECURRING_EVENTS):
        await interaction.response.send_message(
            "✨ **Recurring Events** is a Premium feature.\n\n"
            "Upgrade with `/upgrade` to unlock recurring events, unlimited events, and more!",
            ephemeral=True,
        )
        return

    # Require a confirmed date
    if not event.confirmed_date or event.confirmed_date == "TBD":
        await interaction.response.send_message(
            "❌ The event must have a confirmed date before setting a recurrence schedule.",
            ephemeral=True,
        )
        return

    rtype = RECURRENCE_TYPE_MAP[recurrence_type]
    event.recurrence = RecurrenceConfig(type=rtype, interval=1)
    events.modify_event(event)

    # Generate first batch of instances immediately
    count = events.generate_recurring_instances(event)

    msg = (
        f"✅ **{event.event_name}** will now repeat "
        f"**{RECURRENCE_DISPLAY[recurrence_type]}**."
    )
    if count:
        msg += f"\n📅 Generated {count} upcoming instance{'s' if count != 1 else ''} for the next 28 days."

    await interaction.response.send_message(msg, ephemeral=True)
