import discord, uuid
from core import utils, events, userdata, conf, bulletins
from datetime import datetime, timedelta
from commands.user import timezone
from commands.event import lists, register as ls, register
 
# ==========================
# Button Components
# ==========================

class EarlierDatesButton(discord.ui.Button):
    def __init__(self, view):
        super().__init__(label="⬅️ Earlier Dates", style=discord.ButtonStyle.secondary)
        self.view_ref = view

    async def callback(self, interaction: discord.Interaction):
        self.view_ref.offset -= 20
        self.view_ref.update_buttons()
        await interaction.response.edit_message(view=self.view_ref)

class LaterDatesButton(discord.ui.Button):
    def __init__(self, view):
        super().__init__(label="Later Dates ➡️", style=discord.ButtonStyle.secondary)
        self.view_ref = view

    async def callback(self, interaction: discord.Interaction):
        self.view_ref.offset += 20
        self.view_ref.update_buttons()
        await interaction.response.edit_message(view=self.view_ref)

class DateButton(discord.ui.Button):
    def __init__(self, label, event_data, parent_view, style=discord.ButtonStyle.secondary):
        super().__init__(label=label, style=style)
        self.slot_label = label
        self.event_data = event_data
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.event_data.organizer:
            await interaction.response.send_message("You're not authorized to modify this.", ephemeral=True)
            return

        if self.slot_label in self.parent_view.selected_dates:
            self.parent_view.selected_dates.remove(self.slot_label)
        else:
            self.parent_view.selected_dates.add(self.slot_label)

        self.parent_view.update_buttons()
        await interaction.response.edit_message(view=self.parent_view)

class SubmitDateButton(discord.ui.Button):
    def __init__(self, event_data, parent_view):
        super().__init__(label="Submit Dates", style=discord.ButtonStyle.primary)
        self.event_data = event_data
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.event_data.organizer:
            await interaction.response.send_message("This isn't your form.", ephemeral=True)
            return

        if not self.parent_view.selected_dates:
            await interaction.response.edit_message(content="❌ **No Dates Selected... Aborting**", view=None)
            return

        self.event_data.slots = sorted(
            list(self.parent_view.selected_dates),
            key=lambda d: datetime.strptime(d, "%A, %m/%d/%y")
        )
        
        user_tz = userdata.get_user_timezone(interaction.user.id)
        if not user_tz:
            await utils.safe_send(
                interaction,
                "❌ Timezone not found. Please set your timezone:",
                view=timezone.RegionSelectView(interaction.user.id)
            )
            user_tz = userdata.get_user_timezone(interaction.user.id)
            

        for date in self.event_data.slots:
            for hour in range(24):
                label = f"{hour % 12 or 12}{'AM' if hour < 12 else 'PM'}"
                datetime_str = f"{date} at {label}"
                try:
                    utc_iso = utils.to_utc_isoformat(datetime_str, user_tz)
                    self.event_data.availability[utc_iso] = {}
                except Exception as e:
                    print(f"Failed to parse {datetime_str}: {e}")

        events.modify_event(self.event_data)

        await interaction.response.edit_message(
            content=f"📅 You have selected the following dates for **{self.event_data.event_name}**:\n" +
                    "\n".join(f"* {d}" for d in self.event_data.slots) +
                    "\nWould you like to propose full day availability or select hours?",
            view=ConfirmAvailabilityView(interaction, self.event_data, user_tz)
        )
        if self.view:
            self.view.stop()

class AllDayButton(discord.ui.Button):
    def __init__(self, event_data, parent_view):
        super().__init__(label="All Day", style=discord.ButtonStyle.success)
        self.event_data = event_data
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.edit_message(
            content=f"✅ **All-day availability proposed for {self.event_data.event_name}.**",
            view=None
        )

class SelectTimesButton(discord.ui.Button):
    def __init__(self, event_data, parent_view):
        super().__init__(label="Select Times", style=discord.ButtonStyle.primary)
        self.event_data = event_data
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        if not self.event_data.slots:
            await interaction.response.send_message("No dates available.", ephemeral=True)
            return
        user_tz_str = self.parent_view.user_tz
        local_slots_by_date = utils.from_utc_to_local(self.event_data.availability, user_tz_str)

        await interaction.response.edit_message(
            content=f"🕐 **Select Times for `{self.event_data.event_name}` \n {self.event_data.slots[0]}:**",
            view=register.PaginatedHourSelectionView(
                event=self.event_data,
                slots_data_by_date=local_slots_by_date,
                user_id = str(interaction.user.id),
                context="global_availability"
            )
        )

# ==========================
# Views
# ==========================

class ConfirmAvailabilityView(discord.ui.View):
    def __init__(self, interaction: discord.Interaction, event_data, user_tz):
        super().__init__(timeout=180)
        self.event_data = event_data
        self.interaction = interaction
        self.user_tz = user_tz
        self.add_item(AllDayButton(event_data, self))
        self.add_item(SelectTimesButton(event_data, self))

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        await self.interaction.edit_original_response(view=self)

class DateSelectionView(discord.ui.View):
    def __init__(self, interaction: discord.Interaction, event_data, target_date=None):
        super().__init__(timeout=300)
        self.interaction = interaction
        self.event_data = event_data
        self.target_date = target_date or datetime.now().date()
        self.offset = -2  # Start 2 days before target
        self.selected_dates = set()
        self.update_buttons()

    def update_buttons(self):
        self.clear_items()
        base_date = self.target_date + timedelta(days=self.offset)
        today = datetime.now().date()

        for row in range(4):
            for col in range(5):
                date = base_date + timedelta(days=row * 5 + col)
                label = date.strftime("%A, %m/%d/%y")
                selected = label in self.selected_dates
                style = discord.ButtonStyle.success if selected else discord.ButtonStyle.secondary

                button = DateButton(label, self.event_data, self, style=style)
                if date < today:
                    button.disabled = True
                self.add_item(button)

        # Navigation Row
        self.add_item(EarlierDatesButton(self))
        self.add_item(SubmitDateButton(self.event_data, self))
        self.add_item(LaterDatesButton(self))

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        await self.interaction.edit_original_response(view=self)

class NewEventModal(discord.ui.Modal, title="Create a new event"):
    event_name_input = discord.ui.TextInput(label="Event Name:", placeholder="Event Name MUST be unique.")
    max_attendees_input = discord.ui.TextInput(label="Maximum Number of Attendees:", required=False, placeholder="Optional: Default is no limit")
    target_date_input = discord.ui.TextInput(label="Target Date: (MM/DD/YY)", required=False, placeholder="Optional: Default is today")

    async def on_submit(self, interaction: discord.Interaction):
        today = datetime.now().date()
        target = self.target_date_input.value
        if target:
            target_date = datetime.strptime(target, "%m/%d/%y").date()
            if target_date < today:
                await interaction.response.send_message(
                "🌀 **Nice try, time traveler!** You can't plan events in the past.\nTry again with a future date. ⏳",
                ephemeral=True
            )
            return
        else:
            target_date = today            

        event_data = events.EventState(
            guild_id=str(interaction.guild_id),
            event_name=self.event_name_input.value,
            event_id=str(uuid.uuid4()),
            max_attendees=self.max_attendees_input.value or 999999999,       
            organizer=interaction.user.id,
            organizer_cname=interaction.user.name,
            confirmed_date="TBD",
            availability={},
            rsvp=[]
        )

        await interaction.response.send_message(
            f"📅 Creating event: **{self.event_name_input.value}**🕐 Select Suggested Date(s):",
            view=DateSelectionView(interaction, event_data, target_date),
            ephemeral=True
        )
