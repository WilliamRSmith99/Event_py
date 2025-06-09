import discord, uuid
from core import utils, events, userdata, conf, bulletins
from datetime import datetime, timedelta
from commands.user import timezone
from commands.event import list as ls

EMOJIS = ['1️⃣', '2️⃣', '3️⃣', '4️⃣', '5️⃣', '6️⃣', '7️⃣', '8️⃣', '9️⃣']
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

def format_discord_timestamp(iso_str: str) -> str:
    """Return a Discord full timestamp (<t:...:f>) from UTC ISO string."""
    dt = datetime.fromisoformat(iso_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return f"<t:{int(dt.timestamp())}:f>"

def group_consecutive_hours_timestamp(availability: dict) -> list[str]:
    """
    Groups adjacent 1-hour UTC slots from event_data.availability.
    Returns strings showing full Discord timestamps with RSVP counts.
    """
    if not availability:
        return []

    # Sort by UTC datetime
    sorted_slots = sorted(
        [(datetime.fromisoformat(ts), ts, len(users)) for ts, users in availability.items()],
        key=lambda x: x[0]
    )

    output = []
    start_dt, start_ts, max_rsvp = sorted_slots[0]
    end_dt = start_dt + timedelta(hours=1)
    end_ts = start_ts

    for i in range(1, len(sorted_slots)):
        current_dt, current_ts, rsvp_count = sorted_slots[i]
        next_end = current_dt + timedelta(hours=1)

        if current_dt <= end_dt + timedelta(minutes=5):  # allow small overlap
            end_dt = next_end
            end_ts = current_ts
            max_rsvp = max(max_rsvp, rsvp_count)
        else:
            output.append(
                f"{format_discord_timestamp(start_ts)} -> {format_discord_timestamp(end_ts)} (RSVPs: {max_rsvp})"
            )
            start_dt, start_ts, max_rsvp = current_dt, current_ts, rsvp_count
            end_dt = next_end
            end_ts = current_ts

    # Final range
    output.append(
        f"{format_discord_timestamp(start_ts)} -> {format_discord_timestamp(end_ts)} (RSVPs: {max_rsvp})"
    )

    return output

def generate_thread_messages(event_data) -> list[tuple[discord.Embed, dict[str, str]]]:
    """
    Returns a list of (embed, emoji_map) tuples.
    - Each embed shows up to 9 time slots with RSVP lists.
    - emoji_map maps emoji to UTC ISO timestamp for that embed.
    """
    all_slots = sorted(event_data.availability.keys())
    grouped_embeds = []

    for i in range(0, len(all_slots), 9):
        chunk = all_slots[i:i + 9]
        emoji_map = {}

        embed = discord.Embed(
            title=f"🗓️ Event Signup – {event_data.event_name}",
            description="React to register for a slot below.",
            color=discord.Color.blue()
        )

        for j, utc_iso in enumerate(chunk):
            emoji = EMOJIS[j]
            emoji_map[emoji] = utc_iso
            timestamp = format_discord_timestamp(utc_iso)
            users_dict = event_data.availability.get(utc_iso, {})

            user_lines = []
            for placement, user in sorted(users_dict.items()):
                if event_data.max_attendees is not None and placement > event_data.max_attendees:
                    user_lines.append(f"⏳ {user}")
                else:
                    user_lines.append(f"✅ {user}")

            field_name = f"{emoji}🕓 {timestamp}"
            if not user_lines:
                field_value = "No signups yet"
            else:
                field_value = "\n".join(user_lines)
                if len(field_value) > 1024:
                    field_value = "\n".join(user_lines[:40]) + f"\n...and {len(user_lines) - 40} more"

            embed.add_field(name=field_name, value=field_value, inline=True)

        grouped_embeds.append((embed, emoji_map))

    return grouped_embeds

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
                print(f"Failed to parse {datetime_str}: {e}")

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
            await interaction.response.edit_message(
                content=f"✅ **Finished setting up available times for {self.event_data.event_name}!**",
                view=None
            )
            ## Create Public event bulletin, if configured
            
            server_config = conf.get_config(self.event_data.guild_id)
            print(getattr(server_config, "bulletin_settings_enabled", False),getattr(server_config, "bulletin_channel", False) )
            if getattr(server_config, "bulletin_settings_enabled", False) and getattr(server_config, "bulletin_channel", False):
                channel = interaction.guild.get_channel(int(server_config.bulletin_channel))
                if not channel:
                    print("channel not found")
                    return  # Skip if channel is not found
                try:
                    proposed_dates = "\n".join(f"• {d}" for d in group_consecutive_hours_timestamp(self.event_data.availability))
                    print(proposed_dates)

                    bulletin_body = (
                        f"📅 **Event:** `{self.event_data.event_name}`\n"
                        f"🙋 **Organizer:** <@{self.event_data.organizer}>\n"
                        f"✅ **Confirmed Date:** *{self.event_data.confirmed_date or 'TBD'}*\n"
                        f"🗓️ **Proposed Dates (Your Timezone - `{user_tz}`):**\n{proposed_dates or '*None yet*'}\n"
                    )

                    print(f"conf:{bulletin_body}")

                    bulletin_msg =await channel.send(content=bulletin_body, view=None)
                    bulletin = bulletins.BulletinMessageEntry(
                        event=self.event_data.event_name,
                        msg_head_id=f"{bulletin_msg.id}" 
                    )   
                    thread_messages = generate_thread_messages(self.event_data)
                    
                    thread = await bulletin_msg.create_thread(
                        name=f"🧵 {self.event_data.event_name} Signups",
                        auto_archive_duration=60,
                        reason="Auto-thread for public event"
                    )
                    bulletin.thread_id = thread.id
                    for embed, map in thread_messages:
                        thread_msg = await thread.send(embed=embed)
                        bulletin.thread_messages[thread_msg.id] = map
                    
                    bulletins.modify_event_bulletin(guild_id=interaction.guild.id, entry=bulletin)
                    await interaction.response.send_message("Posted to #main and created signup thread.", ephemeral=True)

                except Exception as e:
                    print(f"Failed to post bulletin in channel {server_config.bulletin_channel}: {e}")


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
            max_attendees=self.max_attendees_input.value,
            organizer=interaction.user.id,
            organizer_cname=interaction.user.name,
            confirmed_date="TBD",
            slots=slots,
            availability={},
            rsvp=set()
        )

        await interaction.response.send_message(
            f"📅 Creating event: **{self.event_name_input.value}**\n{interaction.user.mention}\n🕐 Suggested Dates:",
            view=ProposedDateSelectionView(interaction, event_data),
            ephemeral=True
        )
