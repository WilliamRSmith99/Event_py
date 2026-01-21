"""
Configuration module for Event Bot.

Loads settings from environment variables with sensible defaults.
"""
import os
from pathlib import Path
from typing import Optional

# =============================================================================
# Environment
# =============================================================================

ENV = os.getenv("ENV", "development")  # development, production

# =============================================================================
# Discord Configuration
# =============================================================================

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

# Optional: Restrict commands to a specific guild (for development/testing)
# If not set, commands sync globally (takes up to 1 hour)
DEV_GUILD_ID: Optional[int] = None
_dev_guild = os.getenv("DEV_GUILD_ID")
if _dev_guild:
    DEV_GUILD_ID = int(_dev_guild)

# =============================================================================
# Data Storage
# =============================================================================

# Base directory for data files
DATA_DIR = Path(os.getenv("DATA_DIR", Path(__file__).parent / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

# =============================================================================
# Logging
# =============================================================================

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_FORMAT = os.getenv(
    "LOG_FORMAT",
    "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
)

# =============================================================================
# Feature Flags / Limits
# =============================================================================

# Free tier limits
FREE_TIER_MAX_EVENTS = int(os.getenv("FREE_TIER_MAX_EVENTS", "2"))

# Premium tier limits
PREMIUM_TIER_MAX_EVENTS = int(os.getenv("PREMIUM_TIER_MAX_EVENTS", "999"))  # effectively unlimited

# =============================================================================
# Stripe Configuration (Phase 5)
# =============================================================================

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
STRIPE_PUBLISHABLE_KEY = os.getenv("STRIPE_PUBLISHABLE_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")

# Stripe Price IDs for subscription plans
STRIPE_PRICE_MONTHLY = os.getenv("STRIPE_PRICE_MONTHLY")  # e.g., price_xxx
STRIPE_PRICE_YEARLY = os.getenv("STRIPE_PRICE_YEARLY")    # e.g., price_yyy

# URLs for Stripe checkout
STRIPE_SUCCESS_URL = os.getenv("STRIPE_SUCCESS_URL", "https://discord.com/channels/@me")
STRIPE_CANCEL_URL = os.getenv("STRIPE_CANCEL_URL", "https://discord.com/channels/@me")

# Web server for webhooks
WEB_HOST = os.getenv("WEB_HOST", "0.0.0.0")
WEB_PORT = int(os.getenv("WEB_PORT", "8080"))
WEB_BASE_URL = os.getenv("WEB_BASE_URL", f"http://localhost:{WEB_PORT}")

# =============================================================================
# Validation
# =============================================================================

def validate_config() -> list[str]:
    """
    Validate required configuration.
    Returns a list of error messages (empty if valid).
    """
    errors = []

    if not DISCORD_TOKEN:
        errors.append("DISCORD_TOKEN environment variable is required")

    return errors
