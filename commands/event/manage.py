import discord
from core import auth, events, utils, userdata,bulletins
from commands.event import lists,register
from commands.user import timezone

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
            self.event_details
        )

async def delete_event(interaction: discord.Interaction, guild_id: int, event_name: str = False, event_id: str = False) -> bool:
    if not event_id:
        events_found = events.get_events_by_name(guild_id, event_name)

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
                view = lists.ManageEventView(event, interaction.guild.id, interaction.user)
                await lists.handle_event_message(interaction, event, context="followup",inherit_view=view)

            return False

        else:
                event_name_exact, event_details = lists(events_found.items())[0]
                await _prompt_event_deletion(interaction, guild_id, event_details)
                return True
    else:
        event_details = events.get_event_by_id(guild_id=guild_id, event_id=event_id)
        await _prompt_event_deletion(interaction, guild_id, event_details)
        return True


async def _prompt_event_deletion(interaction, guild_id, event_details, return_on_cancel=None):
    if not await auth.authenticate(interaction, event_details.organizer, "admin"):
        await interaction.response.send_message("❌ You don’t have permission to delete this event.", ephemeral=True)
        return

    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=True)

    async def handle_yes(inter: discord.Interaction):
        if not await auth.authenticate(inter, event_details.organizer, "admin"):
            await inter.response.send_message("❌ You don’t have permission to delete this event.", ephemeral=True)
            return

        if event_details.bulletin_message_id:
            bulletins.delete_event_bulletin(guild_id,event_details.bulletin_message_id)
        result = events.delete_event(guild_id, event_details.event_id)
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

async def handle_confirm_dates(interaction: discord.Interaction, event_id: str, context: str):
    if context not in {"command", "local", "public"}:
        await interaction.response.send_message("❌ Invalid context provided.", ephemeral=True)
        return

    event = events.get_event_by_id(interaction.guild.id,event_id)
    if not event:
        await interaction.response.send_message("❌ Event not found.", ephemeral=True)
        return
    
    user_tz = userdata.get_user_timezone(interaction.user.id)
    if not user_tz:
        await utils.safe_send(
            interaction,
            "❌ Timezone not found. Please set your timezone:",
            view=timezone.RegionSelectView(interaction.user.id)
        )
        user_tz = userdata.get_user_timezone(interaction.user.id)

    slots_data_by_date =  utils.from_utc_to_local(event.availability, user_tz)
    admin_id = interaction.user.id
    view = register.PaginatedHourSelectionView(
        event=event,
        slots_data_by_date=slots_data_by_date,
        user_id=admin_id,
        context="confirm"
    )
    msg_content = "**Select dates and times to confirm:**"
    if context in {"command", "public"}:
        await interaction.response.send_message(content=msg_content, view=view, ephemeral=True)
    elif context == "local":
        await interaction.response.edit_message(content=msg_content, view=view)