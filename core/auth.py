import discord
from discord.ui import View, Button
from typing import Callable, Awaitable, Optional
from core import conf
# Role names considered trusted for elevated permissions
TRUSTED_ROLE_NAMES = ["Admin", "Moderator", "Event Organizer", "Host"]

async def authenticate(interaction: discord.Interaction, organizer_id: int, auth_level: str) -> bool:
    """
    Returns True if the user is the event organizer or holds a trusted role.
    """
    admin_roles=[]
    organizer_roles=[]
    attendee_roles=[]
    guild_config = conf.get_config(interaction.guild.id)
    if guild_config and guild_config.roles_and_permissions_settings_enabled:
        admin_roles = guild_config.admin_roles
        organizer_roles = guild_config.event_organizer_roles
        attendee_roles = guild_config.event_attendee_roles
    # Organizer check
    if interaction.user.id == organizer_id:
        return True

    match auth_level:
            case "admin":
                for role in interaction.user.roles:
                    if role.name in TRUSTED_ROLE_NAMES or role.id in admin_roles or role.name in organizer_roles:                        
                        return True
                return False
            case "organizer":
                for role in interaction.user.roles:
                    if role.name in TRUSTED_ROLE_NAMES or role.name in organizer_roles:
                        return True
                return False
            case "attendee":
                for role in interaction.user.roles:
                    if role.name in TRUSTED_ROLE_NAMES or role.name in attendee_roles:
                        return True
                return False
    # Trusted role check
    

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
        await interaction.edit_original_response(content=prompt, view=view)
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
