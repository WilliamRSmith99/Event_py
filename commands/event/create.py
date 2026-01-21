import discord, uuid
from core import utils, events, userdata, conf, bulletins, entitlements
from core.logging import get_logger, log_event_action
from core.exceptions import EventLimitReachedError, EventAlreadyExistsError
from datetime import datetime, timedelta
from commands.user import timezone
from commands.event import list as ls

logger = get_logger(__name__)


def GenerateProposedDates(target: str = None):
    today = datetime.now().date()

    if target:
        target_date = datetime.strptime(target, "%m/%d/%y").date()
        if target_date < today:
            return None
    else:
        target_date = today

    # Start of week = Sunday
    calendar_start = target_date - timedelta(days=(target_date.weekday() + 1) % 7)

    return [
        (calendar_start + timedelta(days=i)).strftime("%A, %m/%d/%y")
        for i in range(14)
    ]

# ==========================
# Button Components
# ==========================

class DateButton(discord.ui.Button):
    def __init__(self, label, event_data, parent_view, style=discord.ButtonStyle.secondary):
        super().__init__(label=label, style=style, custom_id=str(uuid.uuid4()))
        self.slot_label = label
        self.event_data = event_data
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.event_data.organizer:
            await interaction.response.send_message("You're not authorized to modify this.", ephemeral=True)
            return

        if self.slot_label in self.parent_view.selected_slots:
            self.parent_view.selected_slots.remove(self.slot_label)
        else:
            self.parent_view.selected_slots.add(self.slot_label)

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

        if not self.parent_view.selected_slots:
            await interaction.response.edit_message(content="❌ **No Dates Selected... Aborting**", view=None)
            return

        # Determine removed dates and clear their availability
        previously_selected_dates = set(self.event_data.slots)
        new_selected_dates = set(self.parent_view.selected_slots)
        removed_dates = previously_selected_dates - new_selected_dates

        for date_str in removed_dates:
            self.event_data.availability.pop(date_str, None)

        # Update slots to reflect new selection
        self.event_data.slots = list(new_selected_dates)
        
        try:
            sorted_dates = sorted(
                self.event_data.slots,
                key=lambda d: datetime.strptime(d, "%A, %m/%d/%y")
            )
        except ValueError:
            sorted_dates = sorted(self.event_data.slots)
        self.event_data.slots = sorted_dates
        first_date = sorted_dates[0]

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

        if not self.parent_view.selected_slots:
            await interaction.response.edit_message(
                content="❌ No times selected.",
                view=self.parent_view
            )
            return

        user_tz = userdata.get_user_timezone(interaction.user.id)
        if not user_tz:
            await utils.safe_send(
                interaction,
                "❌ Oh no! We can't find your timezone. Select your timezone to register new events: ",
                view=timezone.RegionSelectView(interaction.user.id)
            )
            return

        for hour_label in self.parent_view.selected_slots:
            try:
                datetime_str = f"{self.date} at {hour_label}"
                utc_iso = utils.to_utc_isoformat(datetime_str, user_tz)
                self.event_data.availability[utc_iso] = {}

            except Exception as e:
                logger.warning(f"Failed to parse datetime: {datetime_str}", exc_info=e)

        events.modify_event(self.event_data)
        
        remaining_dates = list(self.event_data.slots)
        current_index = remaining_dates.index(self.date)

        if current_index + 1 < len(remaining_dates):
            next_date = remaining_dates[current_index + 1]
            await interaction.response.edit_message(
                content=f"🕐 **Select Times for {self.event_data.event_name} on {next_date}:**",
                view=ProposedTimeSelectionView(interaction, self.event_data, next_date)
            )
        else:
            ## Create Public event bulletin, if configured
            server_config = conf.get_config(self.event_data.guild_id)
            if getattr(server_config, "bulletin_settings_enabled", False) and getattr(server_config, "bulletin_channel", False):
                await bulletins.generate_new_bulletin(interaction, event_data=self.event_data,server_config=server_config)
            else:
                await interaction.response.edit_message(
                content=f"✅ **Finished setting up available times for {self.event_data.event_name}!**",
                view=None
            )

        if self.view:
            self.view.stop()

# ==========================
# Views
# ==========================

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

        layout = [self.event_data.slots[i:i+5] for i in range(0, len(self.event_data.slots), 5)]

        for row in layout:
            for date_str in row:
                date_obj = datetime.strptime(date_str, "%A, %m/%d/%y").date()
                is_selected = date_str in self.selected_slots
                style = discord.ButtonStyle.success if is_selected else discord.ButtonStyle.secondary

                button = DateButton(date_str, self.event_data, self, style=style)
                if date_obj < today:
                    button.disabled = True
                self.add_item(button)

        self.add_item(SubmitDateButton(self.event_data, self))

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        await self.interaction.edit_original_response(view=self)

class ProposedTimeSelectionView(discord.ui.View):
    def __init__(self, interaction: discord.Interaction, event_data, date: str):
        super().__init__(timeout=180)
        self.event_data = event_data
        self.date = date
        self.selected_slots = set()
        self.interaction = interaction
        self.update_buttons()

    def update_buttons(self):
        self.clear_items()
        for slot in range(24):
            time_label = f"{slot % 12 or 12}{'AM' if slot < 12 else 'PM'}"
            style = discord.ButtonStyle.success if time_label in self.selected_slots else discord.ButtonStyle.secondary
            self.add_item(DateButton(time_label, self.event_data, self, style=style))

        self.add_item(SubmitTimeButton(self.event_data, self, self.date))

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        await self.interaction.edit_original_response(view=self)

class NewEventModal(discord.ui.Modal, title="Create a new event"):
    event_name_input = discord.ui.TextInput(label="Event Name:", placeholder="Event Name MUST be unique.")
    max_attendees_input = discord.ui.TextInput(label="Maximum Number of Attendees:", required=True, placeholder="0")
    target_date_input = discord.ui.TextInput(label="Target Date: (MM/DD/YY)", required=False, placeholder="Optional: Default is today")

    async def on_submit(self, interaction: discord.Interaction):
        guild_id = interaction.guild_id
        event_name = self.event_name_input.value.strip()

        # Check if event name already exists
        existing_events = events.get_events(guild_id, event_name)
        if existing_events and event_name.lower() in [e.lower() for e in existing_events.keys()]:
            await interaction.response.send_message(
                f"❌ An event named `{event_name}` already exists. Please choose a different name.",
                ephemeral=True
            )
            return

        # Check event limit (free tier = 2 events)
        all_events = events.get_events(guild_id)
        current_count = len(all_events)

        try:
            entitlements.check_event_limit(guild_id, current_count)
        except EventLimitReachedError as e:
            await interaction.response.send_message(e.user_message, ephemeral=True)
            return

        # Validate target date
        slots = GenerateProposedDates(self.target_date_input.value)
        if slots is None:
            await interaction.response.send_message(
                "🌀 **Nice try, time traveler!** You can't plan events in the past.\nTry again with a future date. ⏳",
                ephemeral=True
            )
            return

        event_data = events.EventState(
            guild_id=str(guild_id),
            event_name=event_name,
            max_attendees=self.max_attendees_input.value,
            organizer=interaction.user.id,
            organizer_cname=interaction.user.name,
            confirmed_date="TBD",
            slots=slots,
            availability={},
            rsvp=[]
        )

        log_event_action("create_started", guild_id, event_name, user_id=interaction.user.id)

        await interaction.response.send_message(
            f"📅 Creating event: **{event_name}**\n{interaction.user.mention}\n🕐 Suggested Dates:",
            view=ProposedDateSelectionView(interaction, event_data),
            ephemeral=True
        )
