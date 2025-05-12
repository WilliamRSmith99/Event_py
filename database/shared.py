import asyncio
import discord
from discord import app_commands, Interaction
from discord.ui import View, Button
from typing import Callable, Awaitable, Optional

# Common time slots used across the application
TIME_SLOTS = [
    "12 AM", "1 AM", "2 AM", "3 AM", "4 AM", "5 AM", "6 AM", "7 AM",
    "8 AM", "9 AM", "10 AM", "11 AM", "12 PM", "1 PM", "2 PM", "3 PM",
    "4 PM", "5 PM", "6 PM", "7 PM", "8 PM", "9 PM", "10 PM", "11 PM"
]

# Role names considered trusted for elevated permissions
TRUSTED_ROLE_NAMES = ["Admin", "Moderator", "Event Organizer", "Host"]

async def authenticate(user: discord.User | discord.Member, organizer_id: int) -> bool:
    """
    Returns True if the user is the event organizer or holds a trusted role.
    """
    if isinstance(user, discord.User):
        # We need to fetch the member object to check roles
        return user.id == organizer_id  # fallback: user match only
    
    # Organizer check
    if user.id == organizer_id:
        return True

    # Trusted role check
    for role in user.roles:
        if role.name in TRUSTED_ROLE_NAMES:
            return True

    return False

async def auth(interaction: discord.Interaction) -> bool:
    """
    Check if the user has sufficient permissions to perform privileged actions.
    """
    guild = interaction.guild
    if not guild:
        await interaction.response.send_message("This command must be used in a server.", ephemeral=True)
        return False

    try:
        member = await guild.fetch_member(interaction.user.id)
    except discord.NotFound:
        await interaction.response.send_message("User not found in guild.", ephemeral=True)
        return False
    except Exception as e:
        await interaction.response.send_message(f"Error fetching user info: {e}", ephemeral=True)
        return False

    if member is None:
        return False

    perms = member.guild_permissions
    return perms.administrator or perms.manage_guild or perms.manage_events


async def confirm_action(
    interaction: discord.Interaction,
    prompt: str = "Are you sure?",
    on_success: Optional[Callable[[discord.Interaction], Awaitable[None]]] = None,
    on_cancel: Optional[Callable[[discord.Interaction], Awaitable[None]]] = None,
    edit_message: bool = False,
) -> bool:
    """
    Display a confirmation dialog with Yes/No buttons and invoke callbacks accordingly.
    """
    view = ConfirmActionView(interaction.user)

    if edit_message and not interaction.response.is_done():
        await interaction.response.edit_message(content=prompt, view=view)
    elif edit_message:
        await interaction.followup.send(content=prompt, view=view, ephemeral=True)
    else:
        await safe_respond(interaction, prompt, view=view, ephemeral=True)

    result, button_interaction = await view.wait_for_result()

    if result is True and on_success and button_interaction:
        await on_success(button_interaction)
    elif result is False and on_cancel and button_interaction:
        await on_cancel(button_interaction)

    return result is True


class ConfirmActionView(View):
    """
    A view with Yes/No buttons for user confirmation.
    """
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


async def safe_respond(
    interaction: discord.Interaction,
    content: Optional[str] = None,
    *,
    ephemeral: bool = True,
    view: Optional[View] = None,
    edit_target_message: Optional[discord.Message] = None,
):
    """
    Safely send or edit a message in response to an interaction, avoiding double responses.
    """
    if not content and view is None:
        content = "✅ Done"

    kwargs = {"content": content or "✅ Done"}

    if view:
        if isinstance(view, View) and not view.is_finished():
            kwargs["view"] = view
        else:
            kwargs["view"] = None
    else:
        kwargs["view"] = None

    try:
        if edit_target_message:
            await edit_target_message.edit(**kwargs)
            await interaction.response.defer()
        elif interaction.response.is_done():
            await interaction.edit_original_response(**kwargs)
        else:
            kwargs["ephemeral"] = ephemeral
            await interaction.response.send_message(**kwargs)
    except AttributeError as e:
        if "'NoneType' object has no attribute 'is_finished'" in str(e):
            print("[safe_respond] Suppressed known NoneType.is_finished bug")
        else:
            raise
    except discord.HTTPException as e:
        print(f"[safe_respond] HTTPException fallback: {e}")
        try:
            await interaction.edit_original_response(**kwargs)
        except Exception as ee:
            print(f"[safe_respond] Total failure fallback: {ee}")
