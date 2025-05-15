import discord
from discord.ui import View, Button
from typing import Callable, Awaitable, Optional
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
        await interaction.response.send_message(prompt, view=view, ephemeral=True)

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
