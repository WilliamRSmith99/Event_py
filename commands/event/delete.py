from database import events, shared
import discord

async def delete_event(interaction: discord.Interaction, guild_id: int, event_name: str) -> bool:
    events_found = events.get_events(guild_id, event_name)

    if not events_found:
        await interaction.response.send_message("❌ Failure! Unable to locate event.", ephemeral=True)
        return False

    if len(events_found) == 1:
        event_name_exact, event_details = list(events_found.items())[0]
        await _prompt_event_deletion(interaction, guild_id, event_name_exact, event_details)
        return True

    await interaction.response.send_message(
        f"😬 Oh no! An exact match couldn't be located for `{event_name}`.\n"
        "Did you mean one of these?",
        ephemeral=True
    )

    for matched_name, event in events_found.items():
        view = DeleteEventConfirmView(guild_id, matched_name, event)
        await interaction.followup.send(
            content=f"🗑️ **{event.event_name}** — created by <@{event.organizer}>",
            view=view,
            ephemeral=True
        )

    return False

async def _prompt_event_deletion(interaction, guild_id, event_name, event_details, return_on_cancel=None):
    if not await shared.authenticate(interaction.user, event_details.organizer):
        await interaction.response.send_message("❌ You don’t have permission to delete this event.", ephemeral=True)
        return

    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=True)

    async def handle_yes(inter: discord.Interaction):
        if not await shared.authenticate(inter.user, event_details.organizer):
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
            await return_on_cancel(inter, event_details)
        else:
            msg = await inter.original_response()
            await inter.followup.edit_message(msg.id, content="❌ Deletion cancelled.", view=None)

    await shared.confirm_action(
        interaction,
        f"⚠️ You are about to delete **{event_details.event_name}**.\n\nWould you like to continue?",
        on_success=handle_yes,
        on_cancel=handle_no,
        edit_message=True
    )

    return True

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
