from commands.events import manage
from core.events import EventState
import discord
class DeleteEventConfirmView(discord.ui.View):
    def __init__(self, guild_id: int, event_name: str, event_details: EventState):
        super().__init__(timeout=180)
        self.guild_id = guild_id
        self.event_name = event_name
        self.event_details = event_details

    @discord.ui.button(label="Delete", style=discord.ButtonStyle.danger)
    async def delete_button(self, interaction: discord.Interaction, _):
        await manage._prompt_event_deletion(
            interaction,
            self.guild_id,
            self.event_name,
            self.event_details
        )