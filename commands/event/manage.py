import discord
from core import auth, events
from commands.event import list

# ==========================
#     Delete Event
# ==========================

from commands.event import manage
import discord
class DeleteEventConfirmView(discord.ui.View):
    def __init__(self, guild_id: int, event_name: str, event_details: events.EventState):
        super().__init__(timeout=180)
        self.guild_id = guild_id
        self.event_name = event_name
        self.event_details = event_details

    @discord.ui.button(label="Delete", style=discord.ButtonStyle.danger)
    async def delete_button(self, interaction: discord.Interaction, _):
        await _prompt_event_deletion(
            interaction,
            self.guild_id,
            self.event_name,
            self.event_details
        )

async def delete_event(interaction: discord.Interaction, guild_id: int, event_name: str) -> bool:
    events_found = events.get_events(guild_id, event_name)

    if len(events_found) == 0:
        await interaction.response.send_message("❌ Failure! Unable to locate event.", ephemeral=True)
        return False

    elif len(events_found) > 1:
        await interaction.response.send_message(
            f"😬 Oh no! An exact match couldn't be located for `{event_name}`.\n"
            "Did you mean one of these?",
            ephemeral=True
        )

        for matched_name, event in events_found.items():
            view = list.ManageEventView(event, interaction.guild.id, interaction.user)
            await list.format_single_event(interaction, event, is_edit=False,inherit_view=view)

        return False

    else:
            event_name_exact, event_details = list(events_found.items())[0]
            await _prompt_event_deletion(interaction, guild_id, event_name_exact, event_details)
            return True

async def _prompt_event_deletion(interaction, guild_id, event_name, event_details, return_on_cancel=None):
    if not await auth.authenticate(interaction.user, event_details.organizer):
        await interaction.response.send_message("❌ You don’t have permission to delete this event.", ephemeral=True)
        return

    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=True)

    async def handle_yes(inter: discord.Interaction):
        if not await auth.authenticate(inter.user, event_details.organizer):
            await inter.response.send_message("❌ You don’t have permission to delete this event.", ephemeral=True)
            return

        result = events.delete_event(guild_id, event_name)
        message = (
            f"🪄 Poof! **{event_details.event_name}** successfully deleted"
            if result else
            f"❌ Failure! **{event_details.event_name}** could not be deleted"
        )
        msg = await inter.original_response()
        await inter.followup.edit_message(msg.id, content=message, view=None)

    async def handle_no(inter: discord.Interaction):
        if return_on_cancel:
            await return_on_cancel
        else:
            msg = await inter.original_response()
            await inter.followup.edit_message(msg.id, content="❌ Deletion cancelled.", view=None)

    await auth.confirm_action(
        interaction,
        f"⚠️ You are about to delete **{event_details.event_name}**.\n\nWould you like to continue?",
        on_success=handle_yes,
        on_cancel=handle_no,
        edit_message=True
    )

    return True

# ==========================
#        Edit Event
# ==========================


# ==========================
#       Confirm Event
# ==========================