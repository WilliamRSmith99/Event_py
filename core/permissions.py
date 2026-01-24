"""
Permissions system for Event Bot.

Provides role-based access control integrated with server configuration.
"""
import discord
from discord.ui import View, Button
from typing import Callable, Awaitable, Optional, Union
from enum import Enum

from core.logging import get_logger

logger = get_logger(__name__)


# =============================================================================
# Permission Levels
# =============================================================================

class PermissionLevel(Enum):
    """Permission levels in order of increasing privilege."""
    ATTENDEE = 1      # Can register for events
    ORGANIZER = 2     # Can create and manage their own events
    ADMIN = 3         # Can manage all events and bot settings


# =============================================================================
# Permission Checking
# =============================================================================

def get_user_permission_level(
    member: discord.Member,
    guild_config: "ServerConfigState"
) -> PermissionLevel:
    """
    Determine the highest permission level a member has.

    Args:
        member: The Discord member to check
        guild_config: The server's configuration containing role mappings

    Returns:
        The highest PermissionLevel the user has
    """
    user_role_ids = {role.id for role in member.roles}

    # Check admin roles first (highest privilege)
    if guild_config.admin_roles:
        if user_role_ids & set(guild_config.admin_roles):
            return PermissionLevel.ADMIN

    # Check organizer roles
    if guild_config.event_organizer_roles:
        if user_role_ids & set(guild_config.event_organizer_roles):
            return PermissionLevel.ORGANIZER

    # Check attendee roles
    if guild_config.event_attendee_roles:
        if user_role_ids & set(guild_config.event_attendee_roles):
            return PermissionLevel.ATTENDEE

    # Fallback: If no roles are configured, check Discord permissions
    # Server admins always have admin level
    if member.guild_permissions.administrator:
        return PermissionLevel.ADMIN

    # Default to attendee level (everyone can at least view/register)
    return PermissionLevel.ATTENDEE


def has_permission(
    member: discord.Member,
    guild_config: "ServerConfigState",
    required_level: PermissionLevel
) -> bool:
    """
    Check if a member has at least the required permission level.

    Args:
        member: The Discord member to check
        guild_config: The server's configuration
        required_level: The minimum permission level required

    Returns:
        True if the member has sufficient permissions
    """
    user_level = get_user_permission_level(member, guild_config)
    return user_level.value >= required_level.value


async def check_event_permission(
    user: Union[discord.User, discord.Member],
    guild_id: int,
    organizer_id: int,
    required_level: PermissionLevel = PermissionLevel.ORGANIZER
) -> bool:
    """
    Check if a user has permission to manage an event.

    This is the primary permission check for event operations.
    The event organizer always has permission for their own event.

    Args:
        user: The user attempting the action
        guild_id: The guild where the event exists
        organizer_id: The user ID of the event organizer
        required_level: The minimum permission level required

    Returns:
        True if the user can perform the action
    """
    # Import here to avoid circular imports
    from core.conf import get_config

    # Event organizer always has permission for their own event
    if user.id == organizer_id:
        return True

    # If we only have a User object (not Member), we can only check organizer
    if isinstance(user, discord.User) and not isinstance(user, discord.Member):
        logger.debug(f"User {user.id} is not a Member, can only check organizer match")
        return False

    # Check role-based permissions
    guild_config = get_config(guild_id)
    return has_permission(user, guild_config, required_level)


async def require_permission(
    interaction: discord.Interaction,
    required_level: PermissionLevel,
    organizer_id: Optional[int] = None
) -> bool:
    """
    Check permission and send error message if denied.

    Use this in command handlers for clean permission checks.

    Args:
        interaction: The Discord interaction
        required_level: The minimum permission level required
        organizer_id: Optional organizer ID (user is always allowed for their own event)

    Returns:
        True if permission granted, False if denied (error already sent)
    """
    # Organizer always has access to their own events
    if organizer_id and interaction.user.id == organizer_id:
        return True

    from core.conf import get_config
    guild_config = get_config(interaction.guild_id)

    if not has_permission(interaction.user, guild_config, required_level):
        level_names = {
            PermissionLevel.ATTENDEE: "attendee",
            PermissionLevel.ORGANIZER: "event organizer",
            PermissionLevel.ADMIN: "admin"
        }
        await interaction.response.send_message(
            f"❌ You need **{level_names[required_level]}** permissions to do this.",
            ephemeral=True
        )
        return False

    return True


# =============================================================================
# Legacy Compatibility
# =============================================================================

async def authenticate(user: Union[discord.User, discord.Member], organizer_id: int) -> bool:
    """
    Legacy authentication function for backward compatibility.

    DEPRECATED: Use check_event_permission() instead.

    Returns True if the user is the event organizer or holds a trusted role.
    """
    if user.id == organizer_id:
        return True

    if isinstance(user, discord.User) and not isinstance(user, discord.Member):
        return False

    # Use the new permission system
    from core.conf import get_config

    # We need the guild_id, but legacy calls don't provide it
    # Fall back to checking if user has organizer level or higher
    if hasattr(user, 'guild') and user.guild:
        guild_config = get_config(user.guild.id)
        return has_permission(user, guild_config, PermissionLevel.ORGANIZER)

    return False


# =============================================================================
# Confirmation Dialog
# =============================================================================

async def confirm_action(
    interaction: discord.Interaction,
    prompt: str = "Are you sure?",
    on_success: Optional[Callable[[discord.Interaction], Awaitable[None]]] = None,
    on_cancel: Optional[Callable[[discord.Interaction], Awaitable[None]]] = None,
    edit_message: bool = False,
) -> bool:
    """
    Display a confirmation dialog with Yes/No buttons and invoke callbacks accordingly.

    Args:
        interaction: The Discord interaction
        prompt: The confirmation prompt to display
        on_success: Callback when user confirms
        on_cancel: Callback when user cancels
        edit_message: Whether to edit the existing message instead of sending new

    Returns:
        True if user confirmed, False otherwise
    """
    view = ConfirmActionView(interaction.user)

    if edit_message and not interaction.response.is_done():
        await interaction.response.edit_message(content=prompt, view=view)
    elif edit_message:
        await interaction.followup.send(content=prompt, view=view, ephemeral=True)
    else:
        await interaction.response.send_message(prompt, view=view, ephemeral=True)

    result, button_interaction = await view.wait_for_result()

    if result is True and on_success and button_interaction:
        await on_success(button_interaction)
    elif result is False and on_cancel and button_interaction:
        await on_cancel(button_interaction)

    return result is True


class ConfirmActionView(View):
    """A view with Yes/No buttons for user confirmation."""

    def __init__(self, user: discord.User, timeout: float = 30):
        super().__init__(timeout=timeout)
        self.user = user
        self.result: Optional[bool] = None
        self._interaction: Optional[discord.Interaction] = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.user.id

    @discord.ui.button(label="Yes", style=discord.ButtonStyle.success)
    async def yes(self, interaction: discord.Interaction, button: Button):
        self.result = True
        self._interaction = interaction
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        self.stop()

    @discord.ui.button(label="No", style=discord.ButtonStyle.danger)
    async def no(self, interaction: discord.Interaction, button: Button):
        self.result = False
        self._interaction = interaction
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        self.stop()

    async def wait_for_result(self) -> tuple[Optional[bool], Optional[discord.Interaction]]:
        await self.wait()
        return self.result, self._interaction
