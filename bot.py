import discord
from discord import app_commands
from typing import Optional
import os
from commands import create_event, register, view_responses
from commands.event import info, edit, confirm, delete
from commands.timezone import timezone
from database import shared, user_data, events

# Initialize intents and client
intents = discord.Intents.default()
intents.members = True
client = discord.Client(intents=intents)
tree = discord.app_commands.CommandTree(client)

# Define the specific guild for commands
guild = discord.Object(id=1133941192187457576)

# ============================================================
#                        EVENT COMMANDS
# ============================================================

@tree.command(name="newevent", description="Create a new event", guild=guild)
async def new_event(interaction: discord.Interaction):
    """Command to start creating a new event."""
    await interaction.response.send_modal(create_event.NewEventModal())
    
@tree.command(name="events", description="View events", guild=guild)
@app_commands.describe(event_name="Filter by event name")
async def event(interaction: discord.Interaction, event_name: Optional[str] = None):
    """Command to view events, optionally filter by event name."""
    await info.upcomingevents(interaction, event_name)

@tree.command(name="upcoming", description="View all upcoming events", guild=guild)
async def upcomingevents(interaction: discord.Interaction):
    """Command to view all upcoming events."""
    await info.upcomingevents(interaction)
    
@tree.command(name="delete", description="Delete an upcoming event", guild=guild)
@app_commands.describe(event_name="The event name you want to delete.")
async def deteevent(interaction: discord.Interaction, event_name: Optional[str] = None):
    """Command to delete a specific upcoming event."""
    await delete.delete_event(interaction, interaction.guild_id, event_name)

# ============================================================
#                        USER COMMANDS
# ============================================================

@tree.command(name="register", description="Register your availability for an event", guild=guild)
@app_commands.describe(event_name="The short event ID you want to respond to.")
async def schedule(interaction: discord.Interaction, event_name: str):
    """Command to register for an event."""
    await register.schedule_command(interaction, event_name)

@tree.command(name="responses", description="View availability responses for an event", guild=guild)
@app_commands.describe(event_name="The short event ID you want to respond to.")
async def responses(interaction: discord.Interaction, event_name: str):
    """Command to view the availability responses for an event."""
    await view_responses.build_overlap_summary(interaction, event_name, interaction.guild_id)

@tree.command(name="timezone", description="Set and view your current timezone", guild=guild)
async def viewtimezone(interaction: discord.Interaction):
    """Command to set or view user's current timezone."""
    region = user_data.get_user_timezone(interaction.user.id)

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

    if region:
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

@tree.command(name="remindme", description="Schedule a DM reminder for your event", guild=guild)
@app_commands.describe(event_name="The short event ID you want to respond to.")
async def remindme(interaction: discord.Interaction, event_name: str):
    """Command to set a DM reminder for an event."""
    await view_responses.build_overlap_summary(interaction, event_name, interaction.guild_id)

# ============================================================
#                        BOT EVENTS
# ============================================================

@client.event
async def on_ready():
    """Event triggered when the bot is ready and connected."""
    print(f'Logged in as {client.user}')
    await tree.sync(guild=guild)
    print("Slash commands synced.")

# Run the bot
client.run(os.getenv('DISCORD_TOKEN'))
