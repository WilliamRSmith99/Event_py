from database import events, shared
from commands.timezone import timezone
import discord
from database import shared

async def delete_event( interaction: discord.Interaction, guild_id: int, event_name: str) -> bool:
    """
    Attempts to delete an event after checking if the user is the organizer or has elevated permissions.
    Returns True if deletion is authorized and should proceed.
    """
    full_event_name = events.resolve_event_name(guild_id, event_name)
    if not full_event_name:
        # await interaction.response.send_message("❌ Failure! unable to locate event", ephemeral=True)
        await shared.safe_respond(interaction, "❌ Failure! unable to locate event", ephemeral=True)
        return
        
    event_details = events.get_event(guild_id,full_event_name)
    
    async def handle_yes(inter: discord.Interaction):
        result = events.delete_event(guild_id, full_event_name)
        if result:
            # await interaction.response.edit_message(content=f"🪄 Poof! {event_details.event_name} successfully deleted", view=None)
            await shared.safe_respond(inter, f"🪄 Poof! {event_details.event_name} successfully deleted", ephemeral=True, view=None)

        else:
            # await interaction.response.send_message(content=f"❌ Failure! {event_details.event_name} was unable to be deleted", view=None)
            await shared.safe_respond(inter, f"❌ Failure! {event_details.event_name} was unable to be deleted", ephemeral=True, view=None)
        

    async def handle_no(inter: discord.Interaction):
        await shared.safe_respond(
            inter,
            "❌ Deletion cancelled.",
            ephemeral=True,
            view=None
        )

    await shared.confirm_action(
        interaction,
        f"⚠️ You are about to delete **{event_details.event_name}**⚠️\n\nWould you like to continue?",
        on_success=handle_yes,
        on_cancel=handle_no
    )
    
        
    
    
        
    
            
                