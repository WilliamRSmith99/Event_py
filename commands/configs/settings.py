import discord
from discord.ext import commands
from discord.ui import View, Button, RoleSelect, Select
from core import conf
from core.logging import get_logger

logger = get_logger(__name__)

settings_schema = {
    0: ["Roles and Permissions", '\n`Manage who can configure the bot, create events, or RSVP.`\n    • Admin Roles — Can configure bot settings and manage all events.\n   • Event Organizer Roles — Can create and manage their own events.\n   • Event Attendee Roles — Can RSVP to events and receive reminders'],
    1: ["Bulletin", '\n`Configure public event announcements in a specific channel.`\n   • Enable Bulletin Settings — Toggle automatic posting of events to a public channel.\n   • Bulletin Channel — The text channel where announcements will be posted.\n   • Use Threads — Toggle between threaded time slots or a simple register button.'],
    2: ["Display", '\n`Configure Visual and Display Settings`\n   • Time Format — Choose between 12-hour (1:00 PM) or 24-hour (13:00) format.']
}


class PaginatedSettingsView(View):
    def __init__(self, config, guild: discord.Guild, page: int = 0):
        super().__init__(timeout=300)
        self.config = config
        self.guild = guild
        self.page = page
        self.max_page = len(settings_schema) - 1
        self.render_current_page()

    def render_current_page(self):
        self.clear_items()

        label = settings_schema[self.page][0]
        if label == "Roles and Permissions":
            self.add_item(SettingsToggleButton(self, label=label))
            self.add_item(SettingsRoleSelect(self, "Admin Roles"))
            self.add_item(SettingsRoleSelect(self, "Event Organizer Roles"))
            self.add_item(SettingsRoleSelect(self, "Event Attendee Roles"))

        elif label == "Bulletin":
            self.add_item(SettingsToggleButton(self, label=label))
            self.add_item(CustomChannelSelect(self, "Bulletin Channel"))
            self.add_item(BulletinThreadsToggle(self))

        elif label == "Display":
            self.add_item(TimeFormatToggle(self))

        # Recreate nav buttons each time with correct enabled/disabled state
        self.add_item(PreviousButton(self))
        self.add_item(SubmitButton(self))
        self.add_item(NextButton(self))
        self.add_item(CancelButton(self))


class SettingsRoleSelect(RoleSelect):
    def __init__(self, settings_view: PaginatedSettingsView, key: str):
        self.settings_view = settings_view
        self.key = key
        attr_key = key.lower().replace(" ", "_")

        config_values = getattr(settings_view.config, attr_key, [])
        valid_roles = [role for role in settings_view.guild.roles if role.id in config_values]

        super().__init__(
            placeholder=f"Select roles for {key}",
            min_values=0,
            max_values=25,
            default_values=valid_roles,
            disabled=not getattr(self.settings_view.config, "roles_and_permissions_settings_enabled", False)
        )

    async def callback(self, interaction: discord.Interaction):
        attr_key = self.key.lower().replace(" ", "_")
        selected_ids = {role.id for role in self.values}
        setattr(self.settings_view.config, attr_key, list(selected_ids))
        await interaction.response.edit_message(view=self.settings_view)


class CustomChannelSelect(Select):
    def __init__(self, settings_view: PaginatedSettingsView, key: str):
        self.settings_view = settings_view
        self.key = key
        current_channel = getattr(settings_view.config, "bulletin_channel", None)

        options = [
            discord.SelectOption(
                label=channel.name,
                value=str(channel.id),
                default=(channel.id == current_channel)
            )
            for channel in settings_view.guild.text_channels
        ]

        super().__init__(
            placeholder=f"Select a channel for {key}",
            min_values=0,
            max_values=1,
            options=options[:25],
            disabled=not getattr(self.settings_view.config, "bulletin_settings_enabled", False)
        )

    async def callback(self, interaction: discord.Interaction):
        selected_id = int(self.values[0]) if self.values else None
        setattr(self.settings_view.config, "bulletin_channel", selected_id)
        self.settings_view.render_current_page()
        await interaction.response.edit_message(view=self.settings_view)

class SettingsToggleButton(Button):
    def __init__(self, settings_view: PaginatedSettingsView, label: str):
        self.settings_view = settings_view
        self.setting_key = f"{label.lower().replace(' ', '_')}_settings_enabled"
        is_enabled = getattr(settings_view.config, self.setting_key, False)
        # Show "Disable" when enabled, "Enable" when disabled
        self.display_label = f"✅ {label} Enabled" if is_enabled else f"❌ {label} Disabled"
        style = discord.ButtonStyle.success if is_enabled else discord.ButtonStyle.secondary

        super().__init__(label=self.display_label, style=style, row=0)

    async def callback(self, interaction: discord.Interaction):
        current = getattr(self.settings_view.config, self.setting_key, False)
        setattr(self.settings_view.config, self.setting_key, not current)
        self.settings_view.render_current_page()
        await interaction.response.edit_message(view=self.settings_view)


class TimeFormatToggle(Button):
    """Toggle between 12-hour and 24-hour time format."""
    def __init__(self, settings_view: PaginatedSettingsView):
        self.settings_view = settings_view
        use_24hr = getattr(settings_view.config, "use_24hr_time", False)
        label = "🕐 24-hour format (13:00)" if use_24hr else "🕐 12-hour format (1:00 PM)"
        style = discord.ButtonStyle.primary

        super().__init__(label=label, style=style, row=0)

    async def callback(self, interaction: discord.Interaction):
        current = getattr(self.settings_view.config, "use_24hr_time", False)
        setattr(self.settings_view.config, "use_24hr_time", not current)
        self.settings_view.render_current_page()
        await interaction.response.edit_message(view=self.settings_view)


class BulletinThreadsToggle(Button):
    """Toggle between threads and simple register button for bulletins."""
    def __init__(self, settings_view: PaginatedSettingsView):
        self.settings_view = settings_view
        use_threads = getattr(settings_view.config, "bulletin_use_threads", True)
        label = "📋 Using Threads" if use_threads else "📋 Using Register Button"
        style = discord.ButtonStyle.success if use_threads else discord.ButtonStyle.secondary
        # Disable if bulletin settings are not enabled
        disabled = not getattr(settings_view.config, "bulletin_settings_enabled", False)

        super().__init__(label=label, style=style, row=2, disabled=disabled)

    async def callback(self, interaction: discord.Interaction):
        current = getattr(self.settings_view.config, "bulletin_use_threads", True)
        setattr(self.settings_view.config, "bulletin_use_threads", not current)
        self.settings_view.render_current_page()
        await interaction.response.edit_message(view=self.settings_view)


class PreviousButton(Button):
    def __init__(self, settings_view: PaginatedSettingsView):
        self.settings_view = settings_view
        super().__init__(label="Previous", style=discord.ButtonStyle.secondary, row=4, disabled=settings_view.page == 0)

    async def callback(self, interaction: discord.Interaction):
        if self.settings_view.page > 0:
            self.settings_view.page -= 1
            self.settings_view.render_current_page()
            await interaction.response.edit_message(
                content=f"⚙️ **Settings - {settings_schema[self.settings_view.page][0]}**"+f"{settings_schema[self.settings_view.page][1]}",
                view=self.settings_view
            )


class NextButton(Button):
    def __init__(self, settings_view: PaginatedSettingsView):
        self.settings_view = settings_view
        super().__init__(label="Next", style=discord.ButtonStyle.secondary, row=4, disabled=settings_view.page == settings_view.max_page)

    async def callback(self, interaction: discord.Interaction):
        if self.settings_view.page < self.settings_view.max_page:
            self.settings_view.page += 1
            self.settings_view.render_current_page()
            await interaction.response.edit_message(
                content=f"⚙️ **Settings - {settings_schema[self.settings_view.page][0]}**"+f"{settings_schema[self.settings_view.page][1]}",
                view=self.settings_view
            )


class CancelButton(Button):
    def __init__(self, settings_view: PaginatedSettingsView):
        self.settings_view = settings_view
        super().__init__(label="Cancel", style=discord.ButtonStyle.danger, row=4)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.edit_message(content="❌ Settings configuration cancelled.", view=None)


class SubmitButton(Button):
    def __init__(self, settings_view: PaginatedSettingsView):
        self.settings_view = settings_view
        super().__init__(label="Submit", row=4, style=discord.ButtonStyle.success)

    async def callback(self, interaction: discord.Interaction):
        conf.modify_config(self.settings_view.config)

        # Update all bulletins in this guild to reflect new settings (e.g., time format)
        try:
            from core import events, bulletins
            all_events = events.get_active_events(interaction.guild_id)
            updated = 0
            for event in all_events.values():
                if event.bulletin_message_id:
                    await bulletins.update_bulletin_header(interaction.client, event)
                    updated += 1
            if updated > 0:
                await interaction.response.edit_message(
                    content=f"✅ Settings saved successfully! Updated {updated} bulletin(s).",
                    view=None
                )
                return
        except Exception as e:
            logger.warning(f"Failed to update bulletin after settings save: {e}")

        await interaction.response.edit_message(content="✅ Settings saved successfully!", view=None)


async def PaginatedSettingsContext(interaction: discord.Interaction, guild_id: int, page_num: int = 0):
    config = conf.get_config(guild_id)
    if not config:
        config = conf.ServerConfigState(guild_id)

    guild = interaction.guild
    view = PaginatedSettingsView(config, guild, page_num)
    await interaction.response.send_message(
        content=f"⚙️ **Settings - {settings_schema[page_num][0]}**"+f"{settings_schema[page_num][1]}",
        view=view,
        ephemeral=True
    )
