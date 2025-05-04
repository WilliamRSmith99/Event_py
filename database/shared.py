import discord
from discord import app_commands, Interaction
from discord.ui import View, Button
from typing import Callable, Awaitable, Optional


TIME_SLOTS = [
    "12 AM", "1 AM", "2 AM", "3 AM", "4 AM", "5 AM", "6 AM", "7 AM",
    "8 AM", "9 AM", "10 AM", "11 AM", "12 PM", "1 PM", "2 PM", "3 PM",
    "4 PM", "5 PM", "6 PM", "7 PM", "8 PM", "9 PM", "10 PM", "11 PM"
]

# List of role names to trust
TRUSTED_ROLE_NAMES = ["Admin", "Moderator", "Event Organizer", "Host"]

async def auth( interaction: discord.interactions) -> bool:
    """
    Checks if the member has admin-level permissions or a trusted role.
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
) -> bool:
    view = ConfirmActionView(interaction.user)
    await safe_respond(interaction, prompt, view=view, ephemeral=True)
    result = await view.wait_for_result()

    # ✅ Callbacks
    if result is True and on_success:
        await on_success(interaction)
    elif result is False and on_cancel:
        await on_cancel(interaction)

    return result is True

class ConfirmActionView(View):
    def __init__(self, user: discord.User, timeout: float = 30):
        super().__init__(timeout=timeout)
        self.user = user
        self.result: Optional[bool] = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.user.id

    @discord.ui.button(label="Yes", style=discord.ButtonStyle.success)
    async def yes(self, interaction: discord.Interaction, button: Button):
        self.result = True
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        self.stop()  # stops the view and allows wait_for_result to continue

    @discord.ui.button(label="No", style=discord.ButtonStyle.danger)
    async def no(self, interaction: discord.Interaction, button: Button):
        self.result = False
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True)
        self.stop()

    async def wait_for_result(self) -> Optional[bool]:
        await self.wait()
        return self.result
    
    
async def safe_respond(
    interaction: discord.Interaction,
    content: Optional[str] = None,
    *,
    ephemeral: bool = True,
    view: Optional[View] = None,
    edit_target_message: Optional[discord.Message] = None,  # NEW
):
    if not content and view is None:
        content = "✅ Done"

    kwargs = {"content": content or "✅ Done"}

    if view is not None:
        if isinstance(view, View):
            if not view.is_finished():
                kwargs["view"] = view
            else:
                kwargs["view"] = None
        else:
            kwargs["view"] = view
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