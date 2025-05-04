import discord
from discord.ui import Button, View
from datetime import datetime
from database import events
from database.events import parse_utc_availability_key
import pytz

class OverlapSummaryButton(Button):
    def __init__(self, label: str, utc_date_key: str, utc_hour_key: str, user_count: int, row: int):
        super().__init__(
            label=label,
            style=discord.ButtonStyle.primary,
            custom_id=f"show_attendees_{utc_date_key}_{utc_hour_key}_{user_count}",
            row=row
        )
        self.utc_date_key = utc_date_key
        self.utc_hour_key = utc_hour_key
        self.user_count = user_count

    async def callback(self, interaction: discord.Interaction):
        event = self.view.event
        user_ids = event.availability.get(self.utc_date_key, {}).get(self.utc_hour_key, [])
        if not user_ids:
            await interaction.response.edit_message(content="No users registered for this time slot.", view=self.view)
            return

        usernames = []
        for uid in user_ids:
            member = interaction.guild.get_member(int(uid))
            usernames.append(member.display_name if member else f"<@{uid}>")

        dt = parse_utc_availability_key(self.utc_date_key, self.utc_hour_key)
        date_str = dt.strftime("%B %d")
        time_str = dt.strftime("%I:%M %p").lstrip("0")

        attendee_view = AttendeeView(self.view, self.utc_date_key)
        await interaction.response.edit_message(
            content=f"👥 **Users available at {time_str} on {date_str}**:\n- " + "\n- ".join(usernames),
            view=attendee_view
        )

class OverlapSummaryView(View):
    def __init__(self, event, page: int = 0, show_back_button: bool = False):
        super().__init__(timeout=None)
        self.event = event
        self.page = page
        self.show_back_button = show_back_button 

        self.sorted_dates = sorted(event.availability.keys())
        self.per_page = 4  # Each row is a date, so 5 max
        self.total_pages = (len(self.sorted_dates) - 1) // self.per_page + 1

        start = page * self.per_page
        end = start + self.per_page

        for row_idx, utc_date_key in enumerate(self.sorted_dates[start:end]):
            hour_map = event.availability[utc_date_key]
            non_empty = [(hour, users) for hour, users in hour_map.items() if users]

            top_slots = sorted(non_empty, key=lambda x: len(x[1]), reverse=True)
            has_more = len(top_slots) > 4
            
            if has_more:
                display_slots = top_slots[:3]
            else:
                display_slots = top_slots[:4]
                
                

            # First button is the date label (disabled)
            self.add_item(discord.ui.Button(
                label=f"📅 {utc_date_key}", 
                style=discord.ButtonStyle.secondary, 
                disabled=True,
                row=row_idx
            ))

            # Next 3-4 buttons: top overlaps
            for i, (hour_key, users) in enumerate(display_slots):
                dt = parse_utc_availability_key(utc_date_key, hour_key)
                label = dt.strftime("%I:%M %p").lstrip("0") + f" ({len(users)})"
                self.add_item(OverlapSummaryButton(label, utc_date_key, hour_key, len(users), row=row_idx))

            # If more slots exist, add "+ More" as the final button
            if has_more:
                self.add_item(ShowMoreButton(utc_date_key, row=row_idx))

         # If arrived via button, show back button
        if self.show_back_button:
            self.add_item(BackToInfoButton( event))
        
        # Add pagination row only if needed
        if self.total_pages > 1 and (end - start) < 5:
            nav_row = 4
            if page > 0:
                self.add_item(NavButton(self, "◀ Previous", page - 1, self.event, row=nav_row))
            if page < self.total_pages - 1:
                self.add_item(NavButton("Next ▶", page + 1, self.event, row=nav_row))           

class ShowMoreButton(Button):
    def __init__(self, utc_date_key: str, row: int):
        super().__init__(
            label="+ More",
            style=discord.ButtonStyle.secondary,
            custom_id=f"show_more_{utc_date_key}",
            row=row
        )
        self.utc_date_key = utc_date_key

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_message(f"👀 Full availability list for `{self.utc_date_key}` not yet implemented.", ephemeral=True)
        
class NavButton(Button):
    def __init__(self, parent_view, label: str, target_page: int, event, row: int, show_back_button: bool = False):
        super().__init__(label=label, style=discord.ButtonStyle.secondary, row=row)
        self.parent_view = parent_view
        self.target_page = target_page
        self.event = event
        self.show_back_button = show_back_button

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.edit_message(
            content=f"📊 Top availability slots for **{self.event.event_name}** (page {self.target_page + 1})",
            view=OverlapSummaryView(self.event, page=self.target_page, show_back_button=self.parent_view.show_back_button)
        )

class BackToInfoButton(Button):
    def __init__(self, event):
        super().__init__(label="⬅️ Back to Info", style=discord.ButtonStyle.danger, row=4)
        self.event = event

    async def callback(self, interaction: discord.Interaction):
        from commands.event.info import format_single_event  # Avoid circular imports if needed
        await format_single_event(interaction, self.event, is_edit=True)

class AttendeeView(View):
    def __init__(self, original_view: OverlapSummaryView, utc_date_key: str):
        super().__init__(timeout=None)
        self.original_view = original_view
        self.utc_date_key = utc_date_key

    @discord.ui.button(label="Back", style=discord.ButtonStyle.danger, custom_id="back_button", row=4)
    async def back(self, interaction: discord.Interaction, button: Button):
        await interaction.response.edit_message(
            content=f"📊 Top availability slots for **{self.original_view.event.event_name}**",
            view=OverlapSummaryView(self.original_view.event)
        )
        
        
async def build_overlap_summary(interaction: discord.Interaction, event_name: str, guild_id: str):
    full_event_name = events.resolve_event_name(guild_id, event_name)
    if not full_event_name:
        return None, "❌ Event not found."

    event = events.get_event(guild_id, full_event_name)
    if not event:
        return None, "⚠️ Event data missing."

    view = OverlapSummaryView(event)

    if view is not None:
        await interaction.response.send_message(f"📊 Top availability slots for **{event.event_name}**", view=view, ephemeral=True)
    else:
        await interaction.response.send_message(f"📊 Top availability slots for **{event.event_name}**", ephemeral=True)

        
