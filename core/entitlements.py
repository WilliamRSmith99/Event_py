"""
Entitlements and subscription management for Event Bot.

Handles premium tier checks and feature limits.
This module provides the foundation for the freemium model.

Current implementation uses in-memory checks.
Phase 4 will migrate this to SQLite for persistence.
"""
from enum import Enum
from typing import Optional, Dict, Any
from dataclasses import dataclass
from datetime import datetime

import config
from core.logging import get_logger
from core.exceptions import EventLimitReachedError, PremiumRequiredError

logger = get_logger(__name__)


# =============================================================================
# Subscription Tiers
# =============================================================================

class SubscriptionTier(Enum):
    """Available subscription tiers."""
    FREE = "free"
    PREMIUM = "premium"


@dataclass
class SubscriptionInfo:
    """Information about a guild's subscription."""
    guild_id: int
    tier: SubscriptionTier
    expires_at: Optional[datetime] = None
    stripe_customer_id: Optional[str] = None
    stripe_subscription_id: Optional[str] = None

    @property
    def is_active(self) -> bool:
        """Check if the subscription is currently active."""
        if self.tier == SubscriptionTier.FREE:
            return True
        if self.expires_at is None:
            return False
        return datetime.utcnow() < self.expires_at

    @property
    def is_premium(self) -> bool:
        """Check if this is an active premium subscription."""
        return self.tier == SubscriptionTier.PREMIUM and self.is_active


# =============================================================================
# Feature Limits
# =============================================================================

class Feature(Enum):
    """Features that can be limited by tier."""
    MAX_EVENTS = "max_events"
    RECURRING_EVENTS = "recurring_events"
    PERSISTENT_AVAILABILITY = "persistent_availability"
    ADVANCED_NOTIFICATIONS = "advanced_notifications"
    PRIORITY_SUPPORT = "priority_support"


# Feature limits by tier
FEATURE_LIMITS: Dict[SubscriptionTier, Dict[Feature, Any]] = {
    SubscriptionTier.FREE: {
        Feature.MAX_EVENTS: config.FREE_TIER_MAX_EVENTS,
        Feature.RECURRING_EVENTS: False,
        Feature.PERSISTENT_AVAILABILITY: False,
        Feature.ADVANCED_NOTIFICATIONS: False,
        Feature.PRIORITY_SUPPORT: False,
    },
    SubscriptionTier.PREMIUM: {
        Feature.MAX_EVENTS: config.PREMIUM_TIER_MAX_EVENTS,
        Feature.RECURRING_EVENTS: True,
        Feature.PERSISTENT_AVAILABILITY: True,
        Feature.ADVANCED_NOTIFICATIONS: True,
        Feature.PRIORITY_SUPPORT: True,
    },
}


# =============================================================================
# In-Memory Subscription Store (temporary until SQLite migration)
# =============================================================================

# Guild ID -> SubscriptionInfo
_subscriptions: Dict[int, SubscriptionInfo] = {}


def _get_subscription(guild_id: int) -> SubscriptionInfo:
    """
    Get subscription info for a guild.

    Currently returns FREE tier for all guilds.
    Will be replaced with database lookup in Phase 4.
    """
    if guild_id not in _subscriptions:
        _subscriptions[guild_id] = SubscriptionInfo(
            guild_id=guild_id,
            tier=SubscriptionTier.FREE
        )
    return _subscriptions[guild_id]


# =============================================================================
# Public API
# =============================================================================

def is_premium(guild_id: int) -> bool:
    """
    Check if a guild has an active premium subscription.

    Args:
        guild_id: The Discord guild ID

    Returns:
        True if the guild has active premium
    """
    subscription = _get_subscription(guild_id)
    return subscription.is_premium


def get_tier(guild_id: int) -> SubscriptionTier:
    """
    Get the subscription tier for a guild.

    Args:
        guild_id: The Discord guild ID

    Returns:
        The guild's subscription tier
    """
    subscription = _get_subscription(guild_id)
    return subscription.tier


def get_limit(guild_id: int, feature: Feature) -> Any:
    """
    Get the limit for a specific feature based on the guild's tier.

    Args:
        guild_id: The Discord guild ID
        feature: The feature to check

    Returns:
        The limit value (int for counts, bool for feature flags)
    """
    tier = get_tier(guild_id)
    return FEATURE_LIMITS[tier].get(feature)


def get_event_limit(guild_id: int) -> int:
    """
    Get the maximum number of active events allowed for a guild.

    Args:
        guild_id: The Discord guild ID

    Returns:
        Maximum number of events allowed
    """
    return get_limit(guild_id, Feature.MAX_EVENTS)


def has_feature(guild_id: int, feature: Feature) -> bool:
    """
    Check if a guild has access to a specific feature.

    Args:
        guild_id: The Discord guild ID
        feature: The feature to check

    Returns:
        True if the guild has access to the feature
    """
    limit = get_limit(guild_id, feature)
    if isinstance(limit, bool):
        return limit
    # For numeric limits, return True if limit > 0
    return limit > 0


# =============================================================================
# Enforcement Functions
# =============================================================================

def check_event_limit(guild_id: int, current_count: int) -> None:
    """
    Check if creating a new event would exceed the limit.

    Args:
        guild_id: The Discord guild ID
        current_count: Current number of active events

    Raises:
        EventLimitReachedError: If the limit would be exceeded
    """
    limit = get_event_limit(guild_id)
    if current_count >= limit:
        logger.info(f"Event limit reached for guild {guild_id}: {current_count}/{limit}")
        raise EventLimitReachedError(current_count, limit, guild_id)


def require_premium(guild_id: int, feature_name: str) -> None:
    """
    Require premium for a feature, raising an error if not available.

    Args:
        guild_id: The Discord guild ID
        feature_name: Human-readable feature name for error message

    Raises:
        PremiumRequiredError: If the guild doesn't have premium
    """
    if not is_premium(guild_id):
        logger.info(f"Premium required for '{feature_name}' in guild {guild_id}")
        raise PremiumRequiredError(feature_name)


def require_feature(guild_id: int, feature: Feature) -> None:
    """
    Require a specific feature, raising an error if not available.

    Args:
        guild_id: The Discord guild ID
        feature: The feature to require

    Raises:
        PremiumRequiredError: If the feature is not available
    """
    if not has_feature(guild_id, feature):
        feature_names = {
            Feature.RECURRING_EVENTS: "Recurring Events",
            Feature.PERSISTENT_AVAILABILITY: "Persistent Availability Memory",
            Feature.ADVANCED_NOTIFICATIONS: "Advanced Notifications",
            Feature.PRIORITY_SUPPORT: "Priority Support",
        }
        feature_name = feature_names.get(feature, feature.value)
        raise PremiumRequiredError(feature_name)


# =============================================================================
# Subscription Management (stubs for Phase 5)
# =============================================================================

def activate_premium(
    guild_id: int,
    expires_at: datetime,
    stripe_customer_id: Optional[str] = None,
    stripe_subscription_id: Optional[str] = None
) -> None:
    """
    Activate premium for a guild.

    This will be called by the Stripe webhook handler in Phase 5.

    Args:
        guild_id: The Discord guild ID
        expires_at: When the subscription expires
        stripe_customer_id: Stripe customer ID
        stripe_subscription_id: Stripe subscription ID
    """
    _subscriptions[guild_id] = SubscriptionInfo(
        guild_id=guild_id,
        tier=SubscriptionTier.PREMIUM,
        expires_at=expires_at,
        stripe_customer_id=stripe_customer_id,
        stripe_subscription_id=stripe_subscription_id
    )
    logger.info(f"Premium activated for guild {guild_id} until {expires_at}")


def deactivate_premium(guild_id: int) -> None:
    """
    Deactivate premium for a guild (e.g., subscription canceled or expired).

    Args:
        guild_id: The Discord guild ID
    """
    if guild_id in _subscriptions:
        _subscriptions[guild_id] = SubscriptionInfo(
            guild_id=guild_id,
            tier=SubscriptionTier.FREE
        )
    logger.info(f"Premium deactivated for guild {guild_id}")


def get_subscription_info(guild_id: int) -> SubscriptionInfo:
    """
    Get full subscription information for a guild.

    Args:
        guild_id: The Discord guild ID

    Returns:
        SubscriptionInfo with full details
    """
    return _get_subscription(guild_id)
