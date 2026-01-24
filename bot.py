import discord
from discord import app_commands
from typing import Optional, Literal
import sys
import asyncio

import config
from commands.configs import settings
from commands.event import manage, register, responses, create, list as event_list
from commands.user import timezone, notifications as notif_commands, settings as user_settings
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

@tree.command(name="create", description="Create a new event", guild=guild)
async def create_event(interaction: discord.Interaction):
    """Command to start creating a new event."""
    await interaction.response.send_modal(create.NewEventModal())

@tree.command(name="events", description="View events", guild=guild)
@app_commands.describe(filter="Filter by event name or partial")
async def events_command(interaction: discord.Interaction, filter: Optional[str] = None):
    """Command to view events, optionally filter by event name."""
    await event_list.event_info(interaction, filter)

# ============================================================
#                        USER COMMANDS
# ============================================================

@tree.command(name="settings", description="Configure your personal settings", guild=guild)
async def settings_command(interaction: discord.Interaction):
    await user_settings.user_settings(interaction)

@tree.command(name="server_settings", description="Configure server-wide settings", guild=guild)
async def configure_bot(interaction: discord.Interaction):
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
