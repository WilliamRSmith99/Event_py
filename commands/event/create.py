import discord, uuid, calendar
from discord.ui import View, Button
from datetime import datetime, timedelta, date
from core import utils, events, userdata, conf, bulletins, auth
from commands.user import timezone
from commands.event import lists, register as ls, register
 
# ==========================
# Button Components
# ==========================
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

class AllDayButton(discord.ui.Button):
    def __init__(self, event_data, parent_view):
        super().__init__(label="All Day", style=discord.ButtonStyle.success)
        self.event_data = event_data
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        server_config = conf.get_config(self.event_data.guild_id)
        if not self.event_data.bulletin_message_id and getattr(server_config, "bulletin_settings_enabled", False) and getattr(server_config, "bulletin_channel", False):
            await lists.handle_event_message(interaction, self.event_data,server_config=server_config,context="bulletin")
            await interaction.response.edit_message(
                content=f"✅ Availability updated for **{self.event_data.event_name}**.",
                view=None
            )
        elif self.event_data.bulletin_message_id:
            await bulletins.update_bulletin_header(interaction.client, self.event_data)
            await interaction.response.edit_message(
                content=f"✅ Availability updated for **{self.event_data.event_name}**.",
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
        view = register.PaginatedHourSelectionView(
                event=self.event_data,
                slots_data_by_date=local_slots_by_date,
                user_id = int(interaction.user.id),
                context="global_availability"
            )
        await interaction.response.edit_message(
            content=f"🕐 **Select Times for `{self.event_data.event_name}` \n {self.event_data.slots[0]}:**",
            view=view
        )
        await view.wait()
        selected_dates = view.selected_utc_keys.copy()
        if len(selected_dates) == 0:
            await interaction.edit_original_response(
                content=f"✅ No timeslots selected for **{self.event_data.event_name}**.\n\n *Deleting Event ig* 🫠",
                view=None
            )
            return
        selected_utc_iso_strs = [iso_str for iso_str, _, _ in selected_dates]
        if not await auth.authenticate(interaction, view.event.organizer, "organizer"):
            await interaction.edit_original_response("❌ You don’t have permission to edit this event.", ephemeral=True)
            return
        availability = {}
        for utc_iso_str in selected_utc_iso_strs:
            user_list = self.event_data.availability.get(utc_iso_str, {})
            availability[utc_iso_str] = user_list
        for user in self.event_data.rsvp:
            if events.user_has_any_availability(view.user_id, self.event_data.availability):
                self.event_data.rsvp.append(view.user_id)
            else:
                self.event_data.rsvp.remove(view.user_id)
        self.event_data.availability = availability
        events.modify_event(self.event_data)
        
        server_config = conf.get_config(self.event_data.guild_id)
        if not self.event_data.bulletin_message_id and getattr(server_config, "bulletin_settings_enabled", False) and getattr(server_config, "bulletin_channel", False):
            await lists.handle_event_message(interaction, self.event_data,server_config=server_config,context="bulletin")
            await interaction.edit_original_response(
                content=f"✅ Availability updated for **{self.event_data.event_name}**.",
                view=None
            )
        elif self.event_data.bulletin_message_id:
            await bulletins.update_bulletin_header(interaction.client, self.event_data)
            await interaction.edit_original_response(
                content=f"✅ Availability updated for **{self.event_data.event_name}**.",
                view=None
            )
            

class PrevDatesButton(discord.ui.Button):
    def __init__(self, view):
        super().__init__(label="◀️ Prev Dates", style=discord.ButtonStyle.secondary)
        self.view_ref = view

    async def callback(self, interaction: discord.Interaction):
        if self.view_ref.page == 2:
            self.view_ref.page = 1
        else:
            
            if self.view_ref.current_month == 1:
                self.view_ref.current_month = 12
                self.view_ref.current_year -= 1
            else:
                self.view_ref.current_month -= 1
            self.view_ref.page = 2
        self.view_ref.update_buttons()
        await interaction.response.edit_message(content=self.view_ref.render_date_label(),view=self.view_ref)
        

class NextDatesButton(discord.ui.Button):
    def __init__(self, view):
        super().__init__(label="Next Dates ▶️", style=discord.ButtonStyle.secondary)
        self.view_ref = view

    async def callback(self, interaction: discord.Interaction):
        if self.view_ref.page == 1:
            self.view_ref.page = 2
        else:
            
            if self.view_ref.current_month == 12:
                self.view_ref.current_month = 1
                self.view_ref.current_year += 1
            else:
                self.view_ref.current_month += 1
            self.view_ref.page = 1
        self.view_ref.update_buttons()
        await interaction.response.edit_message(content=self.view_ref.render_date_label(),view=self.view_ref)

class PrevMonthButton(discord.ui.Button):
    def __init__(self, view):
        super().__init__(label="⏪ Prev Month", style=discord.ButtonStyle.secondary)
        self.view_ref = view

    async def callback(self, interaction: discord.Interaction):
        if self.view_ref.current_month == 1:
            self.view_ref.current_month = 12
            self.view_ref.current_year -= 1
        else:
            self.view_ref.current_month -= 1
        
        days_in_prev = calendar.monthrange(
            self.view_ref.current_year, self.view_ref.current_month
        )[1]
        if self.view_ref.page == 2 and days_in_prev <= 16:
            self.view_ref.page = 1
        self.view_ref.update_buttons()
        await interaction.response.edit_message(content=self.view_ref.render_date_label(),view=self.view_ref)
        

class NextMonthButton(discord.ui.Button):
    def __init__(self, view):
        super().__init__(label="Next Month ⏩", style=discord.ButtonStyle.secondary)
        self.view_ref = view

    async def callback(self, interaction: discord.Interaction):
        
        if self.view_ref.current_month == 12:
            self.view_ref.current_month = 1
            self.view_ref.current_year += 1
        else:
            self.view_ref.current_month += 1
        
        days_in_next = calendar.monthrange(
            self.view_ref.current_year, self.view_ref.current_month
        )[1]
        if self.view_ref.page == 2 and days_in_next <= 16:
            self.view_ref.page = 1
        self.view_ref.update_buttons()
        await interaction.response.edit_message(content=self.view_ref.render_date_label(),view=self.view_ref)


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


class DateButton(discord.ui.Button):
    def __init__(self, label, event_data, parent_view, style):
        super().__init__(label=label, style=style)
        self.event_data = event_data
        self.parent_view = parent_view

    async def callback(self, interaction: discord.Interaction):
        # Toggle selection in parent_view.selected_dates
        if interaction.user.id != self.parent_view.event_data.organizer:
            await interaction.response.send_message("This isn't your form.", ephemeral=True)
            return
        if self.label in self.parent_view.selected_dates:
            self.parent_view.selected_dates.remove(self.label)
            self.style = discord.ButtonStyle.secondary
        else:
            self.parent_view.selected_dates.add(self.label)
            self.style = discord.ButtonStyle.success
        self.parent_view.update_buttons()
        await interaction.response.edit_message(view=self.parent_view)

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
        else:
            target_date = today            

        event_data = events.EventState(
            guild_id=str(interaction.guild_id),
            event_name=self.event_name_input.value,
            event_id=str(uuid.uuid4()),
            max_attendees=self.max_attendees_input.value or 999999999,       
            organizer=interaction.user.id,
            organizer_cname=interaction.user.name,
            availability={},
            rsvp=[]
        )
        view = DateSelectionView(interaction, event_data, target_date)
        await interaction.response.send_message(
            content=view.render_date_label(),
            view=view,
            ephemeral=True
        )

class DateSelectionView(discord.ui.View):
    def __init__(self, interaction: discord.Interaction, event_data, target_date: date = None):
        super().__init__(timeout=300)
        self.interaction = interaction
        self.event_data = event_data

        today = datetime.now().date()
        td = target_date or today
        self.current_year = td.year
        self.current_month = td.month
        self.page = 1 if td.day <= 16 else 2

        self.selected_dates = set()
        self.update_buttons()

        

    def update_buttons(self):
        self.clear_items()
        year, month = self.current_year, self.current_month
        month_days = calendar.monthrange(year, month)[1]
        first_of_month = date(year, month, 1)

        if self.page == 1:
            start_day = 1
            count = min(16, month_days)
        else:
            start_day = 17
            count = month_days - 16

        dates = [
            first_of_month + timedelta(days=start_day - 1 + i)
            for i in range(count)
        ]

        today = datetime.now().date()

        for idx in range(16):
            row = idx // 4
            if idx < len(dates):
                d = dates[idx]
                label = d.strftime("%A, %m/%d/%y")
                chosen = label in self.selected_dates
                style = discord.ButtonStyle.success if chosen else discord.ButtonStyle.secondary
                btn = DateButton(label, self.event_data, self, style=style)
                if d < today:
                    btn.disabled = True
                btn.row = row 
                self.add_item(btn)  

        for nav_btn in [
            PrevMonthButton(self),
            PrevDatesButton(self),
            SubmitDateButton(self.event_data, self),
            NextDatesButton(self),
            NextMonthButton(self),
        ]:
            nav_btn.row = 4
            self.add_item(nav_btn)

    def render_date_label(self):
        current_month_str = calendar.month_name[self.current_month]
        return f"📅 **Proposing Dates for:** `{self.event_data.event_name}`\n🗓️ **Month:** {current_month_str} {self.current_year} _(Your local time)_ \n\n\n Select up to **16 dates** for this event.\n Use the navigation buttons below to move through the calendar."
    
    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        await self.interaction.edit_original_response(view=self)