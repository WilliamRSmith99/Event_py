import discord
from discord import app_commands
from typing import Optional, Literal
import sys
import asyncio

import config
from commands.configs import settings
from commands.event import manage, register, responses, create, list as event_list
from commands.user import timezone, notifications as notif_commands
from commands.admin import premium
from core import auth, utils, events, userdata, bulletins, notifications, logging as bot_logging
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

@tree.command(name="new_event", description="Create a new event", guild=guild)
async def new_event(interaction: discord.Interaction):
    """Command to start creating a new event."""
    await interaction.response.send_modal(create.NewEventModal())

@tree.command(name="upcoming_events", description="View events", guild=guild)
@app_commands.describe(filter="Filter by event name or partial")
async def event(interaction: discord.Interaction, filter: Optional[str] = None):
    """Command to view events, optionally filter by event name."""
    await event_list.event_info(interaction, filter)

@tree.command(name="manage_event", description="Organizer and Admin ONLY: Manage an upcoming event", guild=guild)
@app_commands.describe(action='one of "edit", "confirm", "delete"', event_name="The event name you want to manage.")
async def manage_event(interaction: discord.Interaction, event_name: str, action: Literal["edit", "confirm", "delete"]):
    events_match = events.get_events(interaction.guild.id, event_name)
    if len(events_match) == 0:
        await interaction.response.send_message(f"❌ Oh no! No events could be matched for `{event_name}`.\nPlease try again.", ephemeral=True)
        return False

    elif len(events_match) > 1:
        await interaction.response.send_message(
            f"😬 Unable to match a single event for `{event_name}`.\n"
            "Did you mean one of these?",
            ephemeral=True
        )
        # Get user timezone for proper display
        user_tz = userdata.get_user_timezone(interaction.user.id) or "UTC"
        for matched_name, event in events_match.items():
            view = event_list.ManageEventView(event, user_tz, interaction.guild.id, interaction.user)
            await event_list.format_single_event(interaction, event, is_edit=False, inherit_view=view)

        return False

    event_name_exact, event_details = next(iter(events_match.items()))
    match action:
        case "edit":
            await interaction.response.send_message("Editing something...")
        case "confirm":
            await interaction.response.send_message("Action confirmed!")
        case "delete":
            await manage._prompt_event_deletion(interaction, interaction.guild.id, event_name_exact, event_details)
            return True


@tree.command(name="event_responses", description="View availability responses for an event", guild=guild)
@app_commands.describe(event_name="The name of the event you want to view responses for.")
async def event_responses_cmd(interaction: discord.Interaction, event_name: str):
    """Command to view the availability responses for an event."""
    await responses.build_overlap_summary(interaction, event_name, interaction.guild_id)

@tree.command(name="register", description="Register your availability for an event", guild=guild)
@app_commands.describe(event_name="The name of the event you want to register for.")
async def schedule(interaction: discord.Interaction, event_name: str):
    """Command to register for an event."""
    await register.schedule_command(interaction, event_name)

# ============================================================
#                        USER COMMANDS
# ============================================================

@tree.command(name="settings", description="Configure server-wide settings", guild=guild)
async def configure_bot(interaction: discord.Interaction):
    await settings.PaginatedSettingsContext(interaction=interaction, guild_id=interaction.guild_id)

@tree.command(name="timezone", description="Set and view your current timezone", guild=guild)
async def viewtimezone(interaction: discord.Interaction):
    """Command to set or view user's current timezone."""
    region = userdata.get_user_timezone(interaction.user.id)

    async def handle_yes(inter: discord.Interaction):
        await utils.safe_send(
            inter,
            "🌍 Select your timezone region:",
            view=timezone.RegionSelectView(inter.user.id)
        )

    async def handle_no(inter: discord.Interaction):
        await utils.safe_send(
            inter,
            content=f"🌍 Keeping current timezone: `{region}`",
            view=None
        )

    if region:
        await auth.confirm_action(
            interaction,
            f"🌍 Current timezone region: `{region}`\n\nWould you like to set a new region?",
            on_success=handle_yes,
            on_cancel=handle_no
        )
    else:
        await interaction.response.send_message(
            "🌍 Select your timezone region:",
            view=timezone.RegionSelectView(interaction.user.id),
            ephemeral=True
        )

@tree.command(name="remindme", description="Set up notifications for an event", guild=guild)
@app_commands.describe(event_name="The name of the event you want to be reminded for.")
async def remindme(interaction: discord.Interaction, event_name: str):
    """Command to configure notification preferences for an event."""
    await notif_commands.show_notification_settings(interaction, event_name)

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

# ============================================================
#                        BOT EVENTS
# ============================================================

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
        await tree.sync(guild=guild)
        logger.info(f"Slash commands synced to dev guild: {config.DEV_GUILD_ID}")
    else:
        await tree.sync()
        logger.info("Slash commands synced globally (may take up to 1 hour to propagate)")

    await bulletins.restore_bulletin_views(client)

    # Start notification scheduler
    notifications.init_scheduler(client)

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
