"""
Tests for the permission system in core/permissions.py.

Exercises has_permission(), get_user_permission_level(), and require_permission().
Uses make_member / make_interaction helpers from conftest.py.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from core.permissions import (
    PermissionLevel,
    get_user_permission_level,
    has_permission,
    require_permission,
)
from core.conf import ServerConfigState
from tests.conftest import make_member, make_interaction


# ---------------------------------------------------------------------------
# get_user_permission_level
# ---------------------------------------------------------------------------

def make_config(admin_roles=None, organizer_roles=None, attendee_roles=None):
    return ServerConfigState(
        guild_id="12345",
        admin_roles=admin_roles or [],
        event_organizer_roles=organizer_roles or [],
        event_attendee_roles=attendee_roles or [],
    )


def test_admin_role_grants_admin_level():
    member = make_member(role_ids=[99])
    config = make_config(admin_roles=[99])
    assert get_user_permission_level(member, config) == PermissionLevel.ADMIN


def test_organizer_role_grants_organizer_level():
    member = make_member(role_ids=[55])
    config = make_config(organizer_roles=[55])
    assert get_user_permission_level(member, config) == PermissionLevel.ORGANIZER


def test_attendee_role_grants_attendee_level():
    member = make_member(role_ids=[33])
    config = make_config(attendee_roles=[33])
    assert get_user_permission_level(member, config) == PermissionLevel.ATTENDEE


def test_discord_admin_permission_is_admin_level():
    """A Discord server admin with no configured roles still gets ADMIN level."""
    member = make_member(is_admin=True)
    config = make_config()  # no roles configured
    assert get_user_permission_level(member, config) == PermissionLevel.ADMIN


def test_no_roles_and_not_admin_defaults_to_attendee():
    member = make_member()
    config = make_config()
    assert get_user_permission_level(member, config) == PermissionLevel.ATTENDEE


def test_admin_role_takes_precedence_over_organizer():
    """Member has both admin and organizer roles — should get ADMIN."""
    member = make_member(role_ids=[10, 20])
    config = make_config(admin_roles=[10], organizer_roles=[20])
    assert get_user_permission_level(member, config) == PermissionLevel.ADMIN


# ---------------------------------------------------------------------------
# has_permission
# ---------------------------------------------------------------------------

def test_has_permission_passes_when_level_met():
    member = make_member(role_ids=[55])
    config = make_config(organizer_roles=[55])
    assert has_permission(member, config, PermissionLevel.ORGANIZER) is True


def test_has_permission_fails_when_level_not_met():
    member = make_member()  # ATTENDEE level
    config = make_config()
    assert has_permission(member, config, PermissionLevel.ORGANIZER) is False


# ---------------------------------------------------------------------------
# require_permission (async)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_require_permission_blocks_dm_context():
    """Interactions without guild_id (DMs) must be rejected."""
    interaction = make_interaction(guild_id=None)
    result = await require_permission(interaction, PermissionLevel.ATTENDEE)
    assert result is False
    interaction.response.send_message.assert_called_once()
    msg = interaction.response.send_message.call_args[0][0]
    assert "server" in msg.lower()


@pytest.mark.asyncio
async def test_require_permission_passes_for_organizer_role():
    member = make_member(role_ids=[55], user_id=42)
    interaction = make_interaction(guild_id=12345, user=member)

    config = make_config(organizer_roles=[55])
    with patch("core.conf.get_config", return_value=config):
        result = await require_permission(interaction, PermissionLevel.ORGANIZER)
    assert result is True
    interaction.response.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_require_permission_denies_and_sends_message():
    member = make_member(user_id=42)  # ATTENDEE by default
    interaction = make_interaction(guild_id=12345, user=member)

    config = make_config()
    with patch("core.conf.get_config", return_value=config):
        result = await require_permission(interaction, PermissionLevel.ORGANIZER)
    assert result is False
    interaction.response.send_message.assert_called_once()


@pytest.mark.asyncio
async def test_require_permission_passes_for_event_organizer():
    """Even without roles, the event's organizer is always allowed."""
    member = make_member(user_id=999)
    interaction = make_interaction(guild_id=12345, user=member)

    config = make_config()
    with patch("core.conf.get_config", return_value=config):
        result = await require_permission(interaction, PermissionLevel.ORGANIZER, organizer_id=999)
    assert result is True
    interaction.response.send_message.assert_not_called()
