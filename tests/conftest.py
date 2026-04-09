"""
Shared pytest fixtures.

Every test gets a fresh, isolated SQLite database by default (autouse).
Discord objects are mocked via helpers — import them in test files as needed.
"""
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

# Ensure project root is importable from any test file
sys.path.insert(0, str(Path(__file__).parent.parent))


# ---------------------------------------------------------------------------
# Database isolation
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    """
    Patch DB_PATH to a per-test temp file and reset the connection pool.
    Runs automatically for every test — no need to list it as a parameter.
    """
    import core.database as db_mod
    import core.events as events_mod

    db_file = tmp_path / "test.db"
    monkeypatch.setattr(db_mod, "DB_PATH", db_file)
    monkeypatch.setattr(db_mod, "_connection_pool", None)
    # Reset lazy-loaded repo so it binds to the fresh connection
    monkeypatch.setattr(events_mod, "_repo", None)

    db_mod.init_database()

    yield

    db_mod.close_connection()


# ---------------------------------------------------------------------------
# Discord mock helpers (import in tests that need them)
# ---------------------------------------------------------------------------

def make_member(role_ids=None, is_admin=False, user_id=999):
    """Return a mock discord.Member with the given roles."""
    import discord
    member = MagicMock(spec=discord.Member)
    member.id = user_id
    member.roles = []
    for rid in (role_ids or []):
        role = MagicMock()
        role.id = rid
        member.roles.append(role)
    perms = MagicMock()
    perms.administrator = is_admin
    member.guild_permissions = perms
    member.guild = MagicMock()
    member.guild.id = 12345
    return member


def make_interaction(guild_id=12345, user=None):
    """Return a mock discord.Interaction."""
    interaction = MagicMock()
    interaction.guild_id = guild_id
    interaction.user = user or make_member()
    interaction.response = AsyncMock()
    return interaction
