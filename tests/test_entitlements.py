"""
Tests for entitlement / subscription tier logic in core/entitlements.py.

Uses the real (test-isolated) SQLite DB from the fresh_db fixture.
Free tier defaults are read from config.FREE_TIER_MAX_EVENTS (currently 5).
"""
import pytest
import config as app_config

from core.entitlements import (
    Feature,
    FEATURE_LIMITS,
    SubscriptionTier,
    check_event_limit,
    get_event_limit,
    has_feature,
)
from core.exceptions import EventLimitReachedError


GUILD_ID = 99999  # arbitrary guild; no subscription row → FREE tier


# ---------------------------------------------------------------------------
# Free-tier defaults
# ---------------------------------------------------------------------------

def test_free_tier_max_events_is_5():
    assert app_config.FREE_TIER_MAX_EVENTS == 5


def test_free_tier_max_events_reflected_in_feature_limits():
    assert FEATURE_LIMITS[SubscriptionTier.FREE][Feature.MAX_EVENTS] == app_config.FREE_TIER_MAX_EVENTS


def test_free_tier_recurring_events_disabled():
    assert FEATURE_LIMITS[SubscriptionTier.FREE][Feature.RECURRING_EVENTS] is False


def test_free_guild_has_no_recurring_events_feature():
    assert has_feature(GUILD_ID, Feature.RECURRING_EVENTS) is False


# ---------------------------------------------------------------------------
# check_event_limit enforcement
# ---------------------------------------------------------------------------

def test_check_event_limit_passes_under_limit():
    limit = get_event_limit(GUILD_ID)
    # Should not raise when current_count is one below the limit
    check_event_limit(GUILD_ID, limit - 1)  # no exception


def test_check_event_limit_raises_at_limit():
    limit = get_event_limit(GUILD_ID)
    with pytest.raises(EventLimitReachedError) as exc_info:
        check_event_limit(GUILD_ID, limit)
    err = exc_info.value
    assert err.limit == limit
    assert err.current_count == limit


def test_check_event_limit_raises_above_limit():
    limit = get_event_limit(GUILD_ID)
    with pytest.raises(EventLimitReachedError):
        check_event_limit(GUILD_ID, limit + 10)
