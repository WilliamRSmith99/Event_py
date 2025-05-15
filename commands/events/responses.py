import discord
from ui.views import responses

async def build_overlap_summary(interaction: discord.Interaction, event_name: str, guild_id: str):
    event_matches = event.get_events(guild_id, event_name)
    if len(event_matches) == 0:
        return None, "❌ Event not found."
    elif len(event_matches) == 1:
        event = list(event_matches.values())[0]
        view = responses.OverlapSummaryView(event)
        await interaction.response.send_message(f"📊 Top availability slots for **{event.event_name}**", view=view, ephemeral=True)
    else:
        from commands.events.info import format_single_event
        await interaction.response.send_message(
            f"😬 Oh no! An exact match couldn't be located for `{event_name}`.\n"
            "Did you mean one of these?",
            ephemeral=True
        )
        await interaction.response.defer(ephemeral=True, thinking=True)
        for event in event_matches.values():
            await format_single_event(interaction, event, is_edit=False)
