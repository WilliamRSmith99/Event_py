import discord
from discord import app_commands
from typing import Optional, Literal
import os
from commands.event import create, list
from commands.event import manage, register, responses
from commands.user import timezone
from core import auth, user_state, utils, events

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

@tree.command(name="new_event", description="Create a new event", guild=guild)
async def new_event(interaction: discord.Interaction):
    """Command to start creating a new event."""
    await interaction.response.send_modal(create.NewEventModal())
    
@tree.command(name="upcoming_events", description="View events", guild=guild)
@app_commands.describe(filter="Filter by event name or partial")
async def event(interaction: discord.Interaction, filter: Optional[str] = None):
    """Command to view events, optionally filter by event name."""
    await list.event_info(interaction, filter)
    
@tree.command(name="manage_event", description="Organizer and Admin ONLY: Manage an upcoming event", guild=guild)
@app_commands.describe(action='one of "edit", "confirm", "delete"', event_name="The event name you want to manage.")
async def manage_event(interaction: discord.Interaction, event_name: str, action: Literal["edit", "confirm", "delete"]):
    events_match = events.get_events(interaction.guild.id, event_name )
    if len(events_match) == 0:
        await interaction.response.send_message("❌ Oh no! no events could be matched for `{event_name}`.\nPlease try again.", ephemeral=True)
        return False

    elif len(events_match) > 1:
        await interaction.response.send_message(
            f"😬 Oh no! An exact match couldn't be located for `{event_name}`.\n"
            "Did you mean one of these?",
            ephemeral=True
        )
        await interaction.response.defer(ephemeral=True)
        for matched_name, event in events_match.items():
            view = list.ManageEventView(event, interaction.guild.id, interaction.user)
            await list.format_single_event(interaction, event, is_edit=False,inherit_view=view)

        return False

    event_name_exact, event_details = list(events_match.items())[0]
    match action:
        case "edit":
            await interaction.response.send_message("Editing something...")
        case "confirm":
            await interaction.response.send_message("Action confirmed!")
        case "delete":
            await list._prompt_event_deletion(interaction, interaction.guild.id, event_name_exact, event_details)
            return True
    

@tree.command(name="event_responses", description="View availability responses for an event", guild=guild)
@app_commands.describe(event_name="The name of the event you want to view responses for.")
async def responses(interaction: discord.Interaction, event_name: str):
    """Command to view the availability responses for an event."""
    await responses.build_overlap_summary(interaction, event_name, interaction.guild_id)
    
@tree.command(name="register", description="Register your availability for an event", guild=guild)
@app_commands.describe(event_name="The name of the event you want to register for.")
async def schedule(interaction: discord.Interaction, event_name: str):
    """Command to register for an event."""
    await register.schedule_command(interaction, event_name)
# ============================================================
#                        USER COMMANDS
# ============================================================

@tree.command(name="timezone", description="Set and view your current timezone", guild=guild)
async def viewtimezone(interaction: discord.Interaction):
    """Command to set or view user's current timezone."""
    region = user_state.get_user_timezone(interaction.user.id)

    async def handle_yes(inter: discord.Interaction):
        await utils.safe_send(
            inter,
            "🌍 Select your timezone region:",
            view=timezone.RegionSelectView(inter.user.id)
        )

    async def handle_no(inter: discord.Interaction):
        await utils.safe_send(
            inter,
            content=f"🌍 Keeping current timezone: `{region}`",
            view=None
        )

    if region:
        await auth.confirm_action(
            interaction,
            f"🌍 Current timezone region: `{region}`\n\nWould you like to set a new region?",
            on_success=handle_yes,
            on_cancel=handle_no
        )
    else:
        await interaction.response.send_message(
            "🌍 Select your timezone region:",
            view=timezone.RegionSelectView(interaction.user.id),
            ephemeral=True
        )

@tree.command(name="remindme", description="Schedule a DM reminder for your event", guild=guild)
@app_commands.describe(event_name="The name of the event you want to be reminded for.")
async def remindme(interaction: discord.Interaction, event_name: str):
    """Command to set a DM reminder for an event."""
    await responses.build_overlap_summary(interaction, event_name, interaction.guild_id)

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
