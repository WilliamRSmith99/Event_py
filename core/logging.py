"""
Logging configuration for Event Bot.

Provides structured logging with configurable levels and formatting.
"""
import logging
import sys
from typing import Optional

import config

# =============================================================================
# Logger Setup
# =============================================================================

# Track if logging has been configured
_logging_configured = False


def setup_logging() -> None:
    """
    Configure the root logger with the settings from config.
    Should only be called once at startup.
    """
    global _logging_configured
    if _logging_configured:
        return

    # Create formatter
    formatter = logging.Formatter(config.LOG_FORMAT)

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, config.LOG_LEVEL, logging.INFO))

    # Add console handler if not already present
    if not root_logger.handlers:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

    # Reduce noise from discord.py
    logging.getLogger("discord").setLevel(logging.WARNING)
    logging.getLogger("discord.http").setLevel(logging.WARNING)

    _logging_configured = True


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """
    Get a logger instance.

    Args:
        name: Logger name, typically __name__ from the calling module.
              If None, returns the root logger.

    Returns:
        Configured logger instance.
    """
    setup_logging()
    return logging.getLogger(name)


# =============================================================================
# Convenience Functions
# =============================================================================

def log_event_action(
    action: str,
    guild_id: int,
    event_name: str,
    user_id: Optional[int] = None,
    **extra
) -> None:
    """
    Log an event-related action with structured context.

    Args:
        action: The action being performed (e.g., "create", "delete", "register")
        guild_id: The Discord guild ID
        event_name: Name of the event
        user_id: Optional user ID performing the action
        **extra: Additional context to log
    """
    logger = get_logger("events")
    context = {
        "action": action,
        "guild_id": guild_id,
        "event_name": event_name,
    }
    if user_id:
        context["user_id"] = user_id
    context.update(extra)

    logger.info(f"Event action: {action} | {context}")


def log_user_action(
    action: str,
    user_id: int,
    guild_id: Optional[int] = None,
    **extra
) -> None:
    """
    Log a user-related action with structured context.

    Args:
        action: The action being performed (e.g., "set_timezone", "configure")
        user_id: The Discord user ID
        guild_id: Optional guild ID where action occurred
        **extra: Additional context to log
    """
    logger = get_logger("users")
    context = {
        "action": action,
        "user_id": user_id,
    }
    if guild_id:
        context["guild_id"] = guild_id
    context.update(extra)

    logger.info(f"User action: {action} | {context}")


def log_error(
    message: str,
    exc: Optional[Exception] = None,
    **context
) -> None:
    """
    Log an error with optional exception and context.

    Args:
        message: Error description
        exc: Optional exception that was raised
        **context: Additional context to log
    """
    logger = get_logger("errors")
    if exc:
        logger.error(f"{message} | {context}", exc_info=exc)
    else:
        logger.error(f"{message} | {context}")
