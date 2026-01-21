import discord
from discord.ext import commands
from discord.ui import View, Button, RoleSelect, Select
from core import conf

settings_schema = {
    0: ["Roles and Permissions", '\n`Manage who can configure the bot, create events, or RSVP.`\n    • Admin Roles — Can configure bot settings and manage all events.\n   • Event Organizer Roles — Can create and manage their own events.\n   • Event Attendee Roles — Can RSVP to events and receive reminders'],
    1: ["Bulletin", '\n`Configure public event announcements in a specific channel.`\n   • Enable Bulletin Settings — Toggle automatic posting of events to a public channel.\n   • Bulletin Channel — The text channel where announcements will be posted. (Only visible when enabled)'],
    2: ["Display", '\n`Configure Visual and Display Settings`']
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

        elif label == "Display":
            pass

        # Recreate nav buttons each time with correct enabled/disabled state
        self.add_item(PreviousButton(self))
        self.add_item(SubmitButton(self))
        self.add_item(NextButton(self))
        self.add_item(CancelButton(self))


class SettingsRoleSelect(RoleSelect):
    def __init__(self, parent: PaginatedSettingsView, key: str):
        self.parent = parent
        self.key = key
        attr_key = key.lower().replace(" ", "_")

        config_values = getattr(parent.config, attr_key, [])
        valid_roles = [role for role in parent.guild.roles if role.id in config_values]

        super().__init__(
            placeholder=f"Select roles for {key}",
            min_values=0,
            max_values=25,
            default_values=valid_roles,
            disabled=getattr(self.parent.config, "roles_and_permissions_settings_enabled", False)
        )

    async def callback(self, interaction: discord.Interaction):
        attr_key = self.key.lower().replace(" ", "_")
        selected_ids = {role.id for role in self.values}
        setattr(self.parent.config, attr_key, list(selected_ids))
        await interaction.response.edit_message(view=self.parent)


class CustomChannelSelect(Select):
    def __init__(self, parent: PaginatedSettingsView, key: str):
        self.parent = parent
        self.key = key
        current_channel = getattr(parent.config, "bulletin_channel", None)

        options = [
            discord.SelectOption(
                label=channel.name,
                value=str(channel.id),
                default=(channel.id == current_channel)
            )
            for channel in parent.guild.text_channels
        ]

        super().__init__(
            placeholder=f"Select a channel for {key}",
            min_values=0,
            max_values=1,
            options=options[:25],
            disabled=not getattr(self.parent.config, "bulletin_settings_enabled", False)
        )

    async def callback(self, interaction: discord.Interaction):
        selected_id = int(self.values[0]) if self.values else None
        setattr(self.parent.config, "bulletin_channel", selected_id)
        self.parent.render_current_page()
        await interaction.response.edit_message(view=self.parent)

class SettingsToggleButton(Button):
    def __init__(self, parent: PaginatedSettingsView, label: str):
        self.parent = parent
        self.setting_key = f"{label.lower().replace(' ', '_')}_settings_enabled"
        is_enabled = getattr(parent.config, self.setting_key, False)
        # Show "Disable" when enabled, "Enable" when disabled
        self.display_label = f"✅ {label} Enabled" if is_enabled else f"❌ {label} Disabled"
        style = discord.ButtonStyle.success if is_enabled else discord.ButtonStyle.secondary

        super().__init__(label=self.display_label, style=style, row=0)

    async def callback(self, interaction: discord.Interaction):
        current = getattr(self.parent.config, self.setting_key, False)
        setattr(self.parent.config, self.setting_key, not current)
        self.parent.render_current_page()
        await interaction.response.edit_message(view=self.parent)


class PreviousButton(Button):
    def __init__(self, parent: PaginatedSettingsView):
        self.parent = parent
        super().__init__(label="Previous", style=discord.ButtonStyle.secondary, row=4, disabled=parent.page == 0)

    async def callback(self, interaction: discord.Interaction):
        if self.parent.page > 0:
            self.parent.page -= 1
            self.parent.render_current_page()
            await interaction.response.edit_message(
                content=f"⚙️ **Settings - {settings_schema[self.parent.page][0]}**"+f"{settings_schema[self.parent.page][1]}",
                view=self.parent
            )


class NextButton(Button):
    def __init__(self, parent: PaginatedSettingsView):
        self.parent = parent
        super().__init__(label="Next", style=discord.ButtonStyle.secondary, row=4, disabled=parent.page == parent.max_page)

    async def callback(self, interaction: discord.Interaction):
        if self.parent.page < self.parent.max_page:
            self.parent.page += 1
            self.parent.render_current_page()
            await interaction.response.edit_message(
                content=f"⚙️ **Settings - {settings_schema[self.parent.page][0]}**"+f"{settings_schema[self.parent.page][1]}",
                view=self.parent
            )


class CancelButton(Button):
    def __init__(self, parent: PaginatedSettingsView):
        self.parent = parent
        super().__init__(label="Cancel", style=discord.ButtonStyle.danger,row=4)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.edit_message(content="❌ Settings configuration cancelled.", view=None)


class SubmitButton(Button):
    def __init__(self, parent: PaginatedSettingsView):
        self.parent = parent
        super().__init__(label="Submit", row=4, style=discord.ButtonStyle.success)

    async def callback(self, interaction: discord.Interaction):
        conf.modify_config(self.parent.config)
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
