import discord
from discord import app_commands
from typing import Optional
import sys
import asyncio

import config
from commands.configs import settings
from commands.event import register, create, list as event_list, export as event_export, recurrence as event_recurrence
from commands.user import notifications as notif_commands, settings as user_settings
from commands.admin import premium
from core import bulletins, notifications, logging as bot_logging
from core.permissions import require_permission, PermissionLevel
from core.database import init_database
from core.stripe_integration import is_stripe_configured

# =============================================================================
# Validate Configuration
# =============================================================================

config_errors = config.validate_config()
if config_errors:
    for error in config_errors:
        print(f"❌ Config Error: {error}")
    sys.exit(1)

# =============================================================================
# Initialize Logger
# =============================================================================

logger = bot_logging.get_logger(__name__)

# =============================================================================
# Initialize Discord Client
# =============================================================================

intents = discord.Intents.default()
intents.members = True
intents.guilds = True
intents.guild_messages = True
intents.message_content = True
client = discord.Client(intents=intents)
tree = discord.app_commands.CommandTree(client)

# Optional: Restrict to dev guild for faster command sync during development
guild = discord.Object(id=config.DEV_GUILD_ID) if config.DEV_GUILD_ID else None


# ============================================================
#                        EVENT COMMANDS
# ============================================================

@tree.command(name="create", description="Create a new event", guild=guild)
async def create_event(interaction: discord.Interaction):
    """Command to start creating a new event."""
    if not await require_permission(interaction, PermissionLevel.ORGANIZER):
        return
    await interaction.response.send_modal(create.NewEventModal())

@tree.command(name="events", description="View events", guild=guild)
@app_commands.describe(filter="Filter by event name or partial")
async def events_command(interaction: discord.Interaction, filter: Optional[str] = None):
    """Command to view events, optionally filter by event name."""
    await event_list.event_info(interaction, filter)

@tree.command(name="export", description="Export an event to iCal (.ics) for Google Calendar, Outlook, etc.", guild=guild)
@app_commands.describe(event_name="Name of the event to export")
async def export_command(interaction: discord.Interaction, event_name: str):
    await event_export.export_event(interaction, event_name)

@tree.command(name="recurrence", description="Set a recurring schedule for an event (Premium)", guild=guild)
@app_commands.describe(event_name="Name of the event", recurrence_type="How often to repeat")
@app_commands.choices(recurrence_type=[
    app_commands.Choice(name="None (disable)", value="none"),
    app_commands.Choice(name="Weekly", value="weekly"),
    app_commands.Choice(name="Every 2 weeks", value="biweekly"),
    app_commands.Choice(name="Monthly", value="monthly"),
])
async def recurrence_command(interaction: discord.Interaction, event_name: str, recurrence_type: str):
    await event_recurrence.set_recurrence(interaction, event_name, recurrence_type)

# ============================================================
#                        USER COMMANDS
# ============================================================

@tree.command(name="settings", description="Configure your personal settings", guild=guild)
async def settings_command(interaction: discord.Interaction):
    await user_settings.user_settings(interaction)

@tree.command(name="server_settings", description="Configure server-wide settings", guild=guild)
async def configure_bot(interaction: discord.Interaction):
    if not await require_permission(interaction, PermissionLevel.ADMIN):
        return
    await settings.PaginatedSettingsContext(interaction=interaction, guild_id=interaction.guild_id)

# ============================================================
#                      PREMIUM COMMANDS
# ============================================================

@tree.command(name="upgrade", description="View premium features and subscription options", guild=guild)
async def upgrade(interaction: discord.Interaction):
    """Command to view premium features and upgrade options."""
    await premium.show_upgrade_info(interaction)

@tree.command(name="subscription", description="View your server's subscription status", guild=guild)
async def subscription(interaction: discord.Interaction):
    """Command to view subscription status (admin only)."""
    await premium.show_subscription_status(interaction)

@tree.command(name="grant_trial", description="Activate a 30-day premium trial for this server (admin only)", guild=guild)
@app_commands.describe(days="Number of days for the trial (default: 30)")
async def grant_trial(interaction: discord.Interaction, days: Optional[int] = 30):
    """Grant a premium trial to the current guild without requiring Stripe."""
    if not await require_permission(interaction, PermissionLevel.ADMIN):
        return
    await premium.grant_trial(interaction, days)

# ============================================================
#                        BOT EVENTS
# ============================================================

async def _handle_view_attendees(interaction: discord.Interaction, event_name: str):
    """
    View attendees from a bulletin button.
    Confirmed events: show only the confirmed slot's attendees.
    Unconfirmed events: show the full overlap/availability summary.
    """
    from datetime import datetime
    from core import events as core_events, userdata, utils
    from core.utils import format_time

    event_matches = core_events.get_events(interaction.guild_id, event_name)
    if not event_matches:
        await interaction.response.send_message("❌ Event not found.", ephemeral=True)
        return

    event = list(event_matches.values())[0] if len(event_matches) == 1 else None
    if not event:
        # Multiple matches — fall back to overlap summary
        from commands.event.responses import build_overlap_summary
        await build_overlap_summary(interaction, event_name, str(interaction.guild_id))
        return

    if event.confirmed_date and event.confirmed_date != "TBD":
        # Show only confirmed slot attendees
        slot_data = event.availability.get(event.confirmed_date, {})
        user_tz = userdata.get_user_timezone(interaction.user.id) or "UTC"
        use_24hr = userdata.get_effective_time_format(interaction.user.id, interaction.guild_id)

        import pytz
        confirmed_dt = datetime.fromisoformat(event.confirmed_date)
        tz = pytz.timezone(user_tz)
        local_dt = confirmed_dt.replace(tzinfo=pytz.utc).astimezone(tz)
        time_str = format_time(local_dt, use_24hr)
        date_str = local_dt.strftime("%B %d")

        names = []
        for uid in slot_data.values():
            member = interaction.guild.get_member(int(uid))
            names.append(member.display_name if member else f"<@{uid}>")

        content = (
            f"👥 **Registered for {event.event_name}** ({time_str} on {date_str}):\n"
            + ("\n".join(f"- {n}" for n in names) if names else "*No registrations yet.*")
        )
        await interaction.response.send_message(content, ephemeral=True)
    else:
        from commands.event.responses import build_overlap_summary
        await build_overlap_summary(interaction, event_name, str(interaction.guild_id))


async def recurring_event_task():
    """Background task: generates missing recurring event instances every 15 minutes."""
    await client.wait_until_ready()
    while not client.is_closed():
        try:
            from core.repositories.events import EventRepository
            from core import events as core_events
            all_events = EventRepository.get_all_events()
            total_created = 0
            for guild_events in all_events.values():
                for event in guild_events.values():
                    if event.is_recurring and (
                        not event.recurrence or not event.recurrence.parent_event_id
                    ):
                        total_created += core_events.generate_recurring_instances(event)
            if total_created:
                logger.info(f"Recurring task: created {total_created} new instance(s)")
        except Exception as e:
            logger.error(f"Error in recurring event task: {e}", exc_info=True)
        await asyncio.sleep(15 * 60)


@client.event
async def on_interaction(interaction: discord.Interaction):
    """Global interaction handler for persistent button clicks."""
    # Only handle component interactions (buttons, selects)
    if interaction.type != discord.InteractionType.component:
        return

    # Skip if interaction was already responded to (prevents double-handling)
    if interaction.response.is_done():
        return

    custom_id = interaction.data.get("custom_id", "")

    try:
        # Handle bulletin register button
        # Format: register|{event_name} or register|{event_name}|{slot_time}
        # Legacy format: register:{event_name} or register:{event_name}:{slot_time}
        if custom_id.startswith("register|") or custom_id.startswith("register:"):
            delimiter = "|" if "|" in custom_id else ":"
            parts = custom_id.split(delimiter)

            if len(parts) == 2:
                # Main register button: register|{event_name}
                event_name = parts[1]
                await register.schedule_command(interaction, event_name, eph_resp=True)
                return
            elif len(parts) >= 3:
                # Thread slot button: register|{event_name}|{slot_time}
                # Slot time may contain colons (ISO format), so rejoin everything after event_name
                event_name = parts[1]
                slot_time = delimiter.join(parts[2:])
                await interaction.response.defer(ephemeral=True)
                await bulletins.handle_slot_selection(interaction, slot_time, event_name)
                return

        # Handle view attendees button (non-thread bulletins)
        # Format: view_attendees|{event_name}
        if custom_id.startswith("view_attendees|"):
            event_name = custom_id.split("|", 1)[1]
            await _handle_view_attendees(interaction, event_name)
            return

        # Handle notify button
        # Format: notify|{event_name} or notify:{event_name}
        if custom_id.startswith("notify|") or custom_id.startswith("notify:"):
            delimiter = "|" if "|" in custom_id else ":"
            # Event name might contain colons, so only split on first delimiter
            parts = custom_id.split(delimiter, 1)
            if len(parts) >= 2:
                event_name = parts[1]
                await notif_commands.show_notification_settings(interaction, event_name)
                return

    except Exception as e:
        logger.error(f"Error handling interaction {custom_id}: {e}", exc_info=True)
        # Try to respond with error if we haven't already
        if not interaction.response.is_done():
            try:
                await interaction.response.send_message(
                    "❌ An error occurred. Please try again.",
                    ephemeral=True
                )
            except Exception:
                logger.debug("Could not send error response to user after interaction failure")


@client.event
async def on_ready():
    """Event triggered when the bot is ready and connected."""
    logger.info(f"Logged in as {client.user}")

    # Initialize SQLite database
    logger.info("Initializing database...")
    init_database()
    logger.info("Database initialized")

    # Sync slash commands
    if guild:
        # Clear any stale global commands that may conflict with guild commands
        tree.clear_commands(guild=None)
        await tree.sync()  # Sync empty global to Discord
        logger.info("Cleared stale global commands")

        # Now sync guild-specific commands
        await tree.sync(guild=guild)
        logger.info(f"Slash commands synced to dev guild: {config.DEV_GUILD_ID}")
    else:
        await tree.sync()
        logger.info("Slash commands synced globally (may take up to 1 hour to propagate)")

    await bulletins.restore_bulletin_views(client)

    # Start notification scheduler
    notifications.init_scheduler(client)

    # Start recurring event instance generator
    asyncio.create_task(recurring_event_task())

    # Start web server for Stripe webhooks (if configured)
    if is_stripe_configured():
        try:
            from web.server import start_web_server
            asyncio.create_task(start_web_server())
            logger.info(f"Web server started on {config.WEB_HOST}:{config.WEB_PORT}")
        except ImportError:
            logger.warning("Web server dependencies not installed (fastapi, uvicorn)")
    else:
        logger.info("Stripe not configured, web server not started")

    logger.info("Bot is ready!")


# =============================================================================
# Run the Bot
# =============================================================================

if __name__ == "__main__":
    client.run(config.DISCORD_TOKEN)
