import discord, uuid
from database import events, user_data, shared
from commands.timezone import timezone
from datetime import datetime, timedelta

guild=discord.Object(id=1133941192187457576)
user_event_data = {}

def GenerateProposedDates(target: str = None):
    today = datetime.now().date()

    if target:
        target_date = datetime.strptime(target, "%m/%d/%y").date()
        if target_date < today:
            return None  # Signal to abort due to past target
    else:
        target_date = today

    # Align to the start of the week (Sunday)
    days_to_sunday = target_date.weekday() + 1 if target_date.weekday() < 6 else 0
    calendar_start = target_date - timedelta(days=days_to_sunday)

    return [
        (calendar_start + timedelta(days=i)).strftime("%A, %m/%d/%y")
        for i in range(14)
    ]

# Button classes
class dateButton(discord.ui.Button):
    def __init__(self, label, event_data, parent_view, style=discord.ButtonStyle.secondary):
        super().__init__(label=label, style=style)
        self.slot_label = label
        self.event_data = event_data
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        if self.slot_label in self.parent_view.selected_slots:
            self.parent_view.selected_slots.remove(self.slot_label)
        else:
            self.parent_view.selected_slots.add(self.slot_label)

        # Update button styles within the current view
        self.parent_view.update_buttons()
        await interaction.response.edit_message(view=self.parent_view)
class NavButton(discord.ui.Button):
    def __init__(self, label, view, direction):
        super().__init__(label=label, style=discord.ButtonStyle.primary)
        self.parent_view = view  # ✅ use a custom name
        self.direction = direction

    async def callback(self, interaction: discord.Interaction):
        self.parent_view.start_index += self.direction
        self.parent_view.update_buttons()
        await interaction.response.edit_message(view=self.parent_view)
class SubmitDateButton(discord.ui.Button):
    def __init__(self, event_data, parent_view):
        super().__init__(label="Submit Dates", style=discord.ButtonStyle.primary)
        self.event_data = event_data
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.event_data.organizer:
            await interaction.response.edit_message(content="This isn't your form.", view=None)
            return
        
        selected = ", ".join(self.parent_view.selected_slots) or "No dates selected."
        
        if len(self.parent_view.selected_slots) == 0:
            await interaction.response.edit_message(content="❌ **No Dates Selected... Aborting**", view=None)
            return

        # Save the selected dates
        self.event_data.slots = list(self.parent_view.selected_slots)

        # Start picking times for the first date
        first_date = self.event_data.slots[0]
        await interaction.response.edit_message(
            content=f"🕐 **Select Times for {self.event_data.event_name} on {first_date}:**",
            view=ProposedTimeSelectionView(interaction, self.event_data, first_date)
        )

        if self.view:
            self.view.stop()   
class SubmitTimeButton(discord.ui.Button):
    def __init__(self, event_data, parent_view, date):
        super().__init__(label="Submit Times", style=discord.ButtonStyle.primary)
        self.event_data = event_data
        self.parent_view = parent_view
        self.date = date

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.event_data.organizer:
            await interaction.response.edit_message(
                content="This isn't your form.",
                view=None
            )
            return
        if len(self.parent_view.selected_slots) == 0:
            return
        selected = ", ".join(self.parent_view.selected_slots) or "No times selected."

        # Normalize times 
        user_tz = user_data.get_user_timezone(interaction.user.id)
        if not user_tz:
            shared.safe_respond(interaction, "❌ Oh no! We can't find you!\n\nSelect your timezone to register new events:", ephemeral=True, view=timezone.RegionSelectView(interaction.user.id))
        user_tz = user_data.get_user_timezone(interaction.user.id)

        # Strip emojis from the selected date string
        clean_date = self.date.split("📍")[1].strip() if "📍" in self.date else self.date

        # Ensure time is properly formatted
        for hour in self.parent_view.selected_slots:
            # Make sure the hour is in the correct format (e.g., 12AM, 12PM)
            formatted_hour = hour.replace('AM', 'AM').replace('PM', 'PM')
            normalized_datetime =  datetime.fromisoformat(events.to_utc_isoformat(f"{clean_date} at {formatted_hour}", user_tz))
            normalized_date_str = normalized_datetime.strftime("%A, %m/%d/%y")
            normalized_hour_str = normalized_datetime.strftime("%I%p")
            if normalized_date_str not in self.event_data.availability:
                self.event_data.availability[f"{normalized_date_str}"] = {}
            self.event_data.availability[f"{normalized_date_str}"][f"{normalized_hour_str}"] = set()

        events.modify_event(self.event_data)

        # Move to next date or finish
        remaining_dates = list(self.event_data.slots)
        current_index = remaining_dates.index(self.date)
        
        if current_index + 1 < len(remaining_dates):
            next_date = remaining_dates[current_index + 1]
            await interaction.response.edit_message(
                content=f"🕐 **Select Times for {self.event_data.event_name} on {next_date}:**",
                view=ProposedTimeSelectionView(interaction, self.event_data, next_date)
            )
        else:
            # All done
            await interaction.response.edit_message(
                content=f"✅ **Finished setting up available times for {self.event_data.event_name}!**",
                view=None
            )

        if self.view:
            self.view.stop()              
                
# Date View with all the buttons
class ProposedDateSelectionView(discord.ui.View):
    def __init__(self, interaction: discord.Interaction, event_data):
        super().__init__(timeout=300)
        self.event_data = event_data
        self.selected_slots = set()
        self.interaction = interaction

        self.update_buttons()

    def update_buttons(self):
        self.clear_items()

        today = datetime.now().date()
        dates = self.event_data.slots[:14]

        layout = [
            dates[0:5],
            dates[5:7],
            dates[7:12],
            dates[12:14],
        ]

        for row in layout:
            for date_str in row:
                date_obj = datetime.strptime(date_str, "%A, %m/%d/%y").date()
                is_selected = date_str in self.selected_slots
                is_past = date_obj < today

                style = discord.ButtonStyle.success if is_selected else discord.ButtonStyle.secondary
                button = dateButton(date_str, self.event_data, self, style=style)
                if is_past:
                    button.disabled = True
                self.add_item(button)

        self.add_item(SubmitDateButton(self.event_data, self))
        
           
# Hour View with all the buttons
class ProposedTimeSelectionView(discord.ui.View):
    def __init__(self, interaction: discord.Interaction, event_data, date: str):
        super().__init__(timeout=180)
        self.event_data = event_data
        self.date = date
        self.selected_slots = set()

        self.update_buttons()  # Initialize buttons right away

    def update_buttons(self):
        self.clear_items()

        for slot in range(24):  # Loop through 24 hours (slots)
            # Determine time and style (disabled or highlighted)
            time_label = f"{slot%12 or 12}{'AM' if slot < 12 else 'PM'}"
            style = discord.ButtonStyle.secondary  # Default button style
            if time_label in self.selected_slots:
                style = discord.ButtonStyle.success  # Highlight selected times

            button = dateButton(time_label, self.event_data, self, style=style)
            self.add_item(button)

        # Add the Submit button at the end
        self.add_item(SubmitTimeButton(self.event_data, self, self.date))

    async def interaction_check(self, interaction: discord.Interaction):
        """Optional: Add checks for interaction validity."""
        return True

              
# New event modal
class NewEventModal(discord.ui.Modal, title="Create a new event"):
    event_name_input = discord.ui.TextInput(label="Event Name:", placeholder="Event Name MUST be unique.")
    description_input = discord.ui.TextInput(label="Description:",required=False, placeholder="whats it about?")
    target_date_input = discord.ui.TextInput(label="Target Date (MM/DD/YY)",required=False,placeholder="Optional: Default is today")

    async def on_submit(self, interaction: discord.Interaction):
        slots = GenerateProposedDates(self.target_date_input.value)

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
            f"📅 Creating event: **{self.event_name_input.value}**\n {interaction.user}\n🕐 Suggested Dates:",
            view=ProposedDateSelectionView(interaction, event_data),
            ephemeral=True
        )