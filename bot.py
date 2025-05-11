import discord
from discord import app_commands
from typing import Optional
import os
from commands import create_event, register, view_responses
from commands.event import info, edit, confirm, delete
from commands.timezone import timezone
from database import shared, user_data, events

intents = discord.Intents.default()
intents.members = True
client = discord.Client(intents=intents)
tree = discord.app_commands.CommandTree(client)
guild=discord.Object(id=1133941192187457576)

# ============================================================
#                        EVENT COMMANDS
# ============================================================

# Slash command to start new event
@tree.command(name="newevent", description="Create a new event", guild=guild)
async def new_event(interaction: discord.Interaction):
    await interaction.response.send_modal(create_event.NewEventModal())
    
@tree.command(name="events", description="View events", guild=guild)
@app_commands.describe(event_name="Filter by event name")
async def event(interaction: discord.Interaction, event_name: Optional[str] = None):
    await info.upcomingevents(interaction, event_name)
    # await delete.delete_event(interaction, interaction.guild_id, event_name)
    
# Slash command to view all events
@tree.command(name="upcoming", description="view all upcoming events", guild=guild)
async def upcomingevents(interaction: discord.Interaction):
    await info.upcomingevents(interaction)
    
# Slash command to delete an event
@tree.command(name="delete", description="delete an upcoming events", guild=guild)
@app_commands.describe(event_name="The event name you want to delete.")
async def deteevent(interaction: discord.Interaction, event_name: Optional[str] = None):
    await delete.delete_event(interaction, interaction.guild_id, event_name)
    
# ============================================================
#                        USER COMMANDS
# ============================================================
  
# Slash Command to register for event  
@tree.command(name="register", description="Register your availability for an event.", guild=guild)
@app_commands.describe(event_name="The short event ID you want to respond to.")
async def schedule(interaction: discord.Interaction, event_name: str):
    await register.schedule_command(interaction, event_name)

# Slash Command to see responses 
@tree.command(name="responses", description="View availability responses for an event.", guild=guild)
@app_commands.describe(event_name="The short event ID you want to respond to.")
async def schedule(interaction: discord.Interaction, event_name: str):
    await view_responses.build_overlap_summary(interaction ,event_name, interaction.guild_id)
    
# Set and View timezone
@tree.command(name="timezone", description="Set and View your current timezone", guild=guild)
async def viewtimezone(interaction: discord.Interaction):
    region = user_data.get_user_timezone(interaction.user.id)

    if region:
        async def handle_yes(inter: discord.Interaction):
            await shared.safe_respond(
                inter,
                "🌍 Select your timezone region:",
                view=timezone.RegionSelectView(inter.user.id),
                ephemeral=True
            )

        async def handle_no(inter: discord.Interaction):
            await shared.safe_respond(
                inter,
                f"🌍 Keeping current timezone: `{region}`",
                ephemeral=True,
                view=None
            )

        await shared.confirm_action(
            interaction,
            f"🌍 Current timezone region: `{region}`\n\nWould you like to set a new region?",
            on_success=handle_yes,
            on_cancel=handle_no
        )
    else:
        await shared.safe_respond(
            interaction,
            "🌍 Select your timezone region:",
            view=timezone.RegionSelectView(interaction.user.id),
            ephemeral=True
        )

# Slash Command to set personal DM reminders 
@tree.command(name="remindme", description="Schedule a DM reminder for your event", guild=guild)
@app_commands.describe(event_name="The short event ID you want to respond to.")
async def schedule(interaction: discord.Interaction, event_name: str):
    await view_responses.build_overlap_summary(interaction ,event_name, interaction.guild_id)
   

@client.event
async def on_ready():
    print(f'Logged in as {client.user}')
    await tree.sync(guild = guild)
    print("Slash commands synced.")

# Run the bot
client.run(os.getenv('DISCORD_TOKEN'))
