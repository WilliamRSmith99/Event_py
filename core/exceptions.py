"""
Custom exceptions for Event Bot.

These exceptions provide structured error handling with user-friendly messages.
"""
from typing import Optional


class EventBotError(Exception):
    """Base exception for all Event Bot errors."""

    def __init__(self, message: str, user_message: Optional[str] = None):
        """
        Args:
            message: Technical error message for logging
            user_message: User-friendly message to display (defaults to message)
        """
        super().__init__(message)
        self.user_message = user_message or message

    def __str__(self) -> str:
        return self.args[0]


# =============================================================================
# Event Errors
# =============================================================================

class EventNotFoundError(EventBotError):
    """Raised when an event cannot be found."""

    def __init__(self, event_name: str, guild_id: Optional[int] = None):
        self.event_name = event_name
        self.guild_id = guild_id
        super().__init__(
            message=f"Event '{event_name}' not found in guild {guild_id}",
            user_message=f"❌ Event `{event_name}` not found."
        )


class EventAlreadyExistsError(EventBotError):
    """Raised when trying to create an event that already exists."""

    def __init__(self, event_name: str, guild_id: Optional[int] = None):
        self.event_name = event_name
        self.guild_id = guild_id
        super().__init__(
            message=f"Event '{event_name}' already exists in guild {guild_id}",
            user_message=f"❌ An event named `{event_name}` already exists. Please choose a different name."
        )


class EventLimitReachedError(EventBotError):
    """Raised when the server has reached its event limit (free tier)."""

    def __init__(self, current_count: int, limit: int, guild_id: Optional[int] = None):
        self.current_count = current_count
        self.limit = limit
        self.guild_id = guild_id
        super().__init__(
            message=f"Event limit reached: {current_count}/{limit} in guild {guild_id}",
            user_message=(
                f"❌ Event limit reached! You have **{current_count}/{limit}** active events.\n\n"
                "Upgrade to **Premium** for unlimited events, or delete an existing event."
            )
        )


# =============================================================================
# Permission Errors
# =============================================================================

class PermissionDeniedError(EventBotError):
    """Raised when a user lacks permission for an action."""

    def __init__(
        self,
        action: str,
        required_level: Optional[str] = None,
        user_id: Optional[int] = None
    ):
        self.action = action
        self.required_level = required_level
        self.user_id = user_id

        if required_level:
            user_msg = f"❌ You need **{required_level}** permissions to {action}."
        else:
            user_msg = f"❌ You don't have permission to {action}."

        super().__init__(
            message=f"Permission denied: user {user_id} cannot {action} (requires {required_level})",
            user_message=user_msg
        )


class NotEventOrganizerError(PermissionDeniedError):
    """Raised when only the event organizer can perform an action."""

    def __init__(self, event_name: str, user_id: Optional[int] = None):
        self.event_name = event_name
        super().__init__(
            action=f"manage event '{event_name}'",
            required_level="event organizer",
            user_id=user_id
        )
        self.user_message = f"❌ Only the organizer of `{event_name}` can perform this action."


# =============================================================================
# User Errors
# =============================================================================

class TimezoneNotSetError(EventBotError):
    """Raised when a user hasn't set their timezone."""

    def __init__(self, user_id: int):
        self.user_id = user_id
        super().__init__(
            message=f"Timezone not set for user {user_id}",
            user_message="❌ Please set your timezone first using `/timezone`."
        )


class InvalidTimezoneError(EventBotError):
    """Raised when an invalid timezone is provided."""

    def __init__(self, timezone: str):
        self.timezone = timezone
        super().__init__(
            message=f"Invalid timezone: {timezone}",
            user_message=f"❌ `{timezone}` is not a valid timezone. Please select from the list."
        )


# =============================================================================
# Configuration Errors
# =============================================================================

class ConfigurationError(EventBotError):
    """Raised when there's a configuration issue."""

    def __init__(self, message: str, user_message: Optional[str] = None):
        super().__init__(
            message=message,
            user_message=user_message or "❌ There's a configuration issue. Please contact an admin."
        )


class BulletinChannelNotFoundError(ConfigurationError):
    """Raised when the bulletin channel is not found."""

    def __init__(self, channel_id: int, guild_id: int):
        self.channel_id = channel_id
        self.guild_id = guild_id
        super().__init__(
            message=f"Bulletin channel {channel_id} not found in guild {guild_id}",
            user_message="❌ The bulletin channel could not be found. Please reconfigure it in `/settings`."
        )


# =============================================================================
# Premium/Subscription Errors
# =============================================================================

class PremiumRequiredError(EventBotError):
    """Raised when a premium feature is accessed without subscription."""

    def __init__(self, feature: str):
        self.feature = feature
        super().__init__(
            message=f"Premium required for feature: {feature}",
            user_message=(
                f"✨ **{feature}** is a Premium feature.\n\n"
                "Upgrade to unlock unlimited events, recurring events, and more!\n"
                "Use `/upgrade` to learn more."
            )
        )


class SubscriptionExpiredError(EventBotError):
    """Raised when a subscription has expired."""

    def __init__(self, guild_id: int):
        self.guild_id = guild_id
        super().__init__(
            message=f"Subscription expired for guild {guild_id}",
            user_message=(
                "⚠️ Your Premium subscription has expired.\n\n"
                "Your events are safe, but premium features are now disabled.\n"
                "Use `/upgrade` to renew your subscription."
            )
        )
