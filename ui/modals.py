import discord
from commands.events import create as ecreate
from core import events
from ui.views import create
class NewEventModal(discord.ui.Modal, title="Create a new event"):
    event_name_input = discord.ui.TextInput(label="Event Name:", placeholder="Event Name MUST be unique.")
    description_input = discord.ui.TextInput(label="Description:", required=False, placeholder="What’s it about?")
    target_date_input = discord.ui.TextInput(label="Target Date (MM/DD/YY)", required=False, placeholder="Optional: Default is today")

    async def on_submit(self, interaction: discord.Interaction):
        slots = ecreate.GenerateProposedDates(self.target_date_input.value)

        if slots is None:
            await interaction.response.send_message(
                "🌀 **Nice try, time traveler!** You can't plan events in the past.\nTry again with a future date. ⏳",
                ephemeral=True
            )
            return

        event_data = events.EventState(
            guild_id=str(interaction.guild_id),
            event_name=self.event_name_input.value,
            description=self.description_input.value,
            organizer=interaction.user.id,
            organizer_cname=interaction.user.name,
            confirmed_date="TBD",
            slots=slots,
            availability={},
            rsvp=set()
        )

        await interaction.response.send_message(
            f"📅 Creating event: **{self.event_name_input.value}**\n{interaction.user.mention}\n🕐 Suggested Dates:",
            view=create.ProposedDateSelectionView(interaction, event_data),
            ephemeral=True
        )
