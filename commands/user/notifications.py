"""
Notification commands and UI for users.

Allows users to manage their notification preferences for events.
"""
import discord
from discord.ui import View, Button, Select
from typing import Optional

from core import notifications, events
from core.logging import get_logger

logger = get_logger(__name__)


# =============================================================================
# Reminder Time Options
# =============================================================================

REMINDER_OPTIONS = [
    (15, "15 minutes before"),
    (30, "30 minutes before"),
    (60, "1 hour before"),
    (120, "2 hours before"),
    (1440, "1 day before"),
]


# =============================================================================
# Views
# =============================================================================

class NotificationSettingsView(View):
    """View for configuring notification settings for an event."""

    def __init__(
        self,
        user_id: int,
        guild_id: int,
        event_name: str,
        current_pref: Optional[notifications.NotificationPreference] = None
    ):
        super().__init__(timeout=180)
        self.user_id = user_id
        self.guild_id = guild_id
        self.event_name = event_name

        # Current settings (or defaults)
        self.reminder_minutes = current_pref.reminder_minutes if current_pref else 60
        self.notify_on_start = current_pref.notify_on_start if current_pref else True
        self.notify_on_change = current_pref.notify_on_change if current_pref else True
        self.notify_on_cancel = current_pref.notify_on_cancel if current_pref else True
        self.is_enabled = current_pref is not None

        self._build_components()

    def _build_components(self):
        self.clear_items()

        # Reminder time select
        options = [
            discord.SelectOption(
                label=label,
                value=str(minutes),
                default=(minutes == self.reminder_minutes)
            )
            for minutes, label in REMINDER_OPTIONS
        ]

        reminder_select = Select(
            placeholder="Reminder time",
            options=options,
            custom_id="reminder_time",
            row=0
        )
        reminder_select.callback = self._on_reminder_change
        self.add_item(reminder_select)

        # Toggle buttons for notification types
        self.add_item(ToggleButton(
            "Event Start",
            self.notify_on_start,
            "toggle_start",
            row=1
        ))
        self.add_item(ToggleButton(
            "Event Changes",
            self.notify_on_change,
            "toggle_change",
            row=1
        ))
        self.add_item(ToggleButton(
            "Event Canceled",
            self.notify_on_cancel,
            "toggle_cancel",
            row=1
        ))

        # Save/Cancel buttons
        self.add_item(Button(
            label="Save Preferences",
            style=discord.ButtonStyle.success,
            custom_id="save",
            row=2
        ))

        if self.is_enabled:
            self.add_item(Button(
                label="Disable Notifications",
                style=discord.ButtonStyle.danger,
                custom_id="disable",
                row=2
            ))

    async def _on_reminder_change(self, interaction: discord.Interaction):
        self.reminder_minutes = int(interaction.data["values"][0])
        self._build_components()
        await interaction.response.edit_message(view=self)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "This isn't your notification settings!",
                ephemeral=True
            )
            return False

        custom_id = interaction.data.get("custom_id", "")

        if custom_id == "toggle_start":
            self.notify_on_start = not self.notify_on_start
            self._build_components()
            await interaction.response.edit_message(view=self)
            return False

        if custom_id == "toggle_change":
            self.notify_on_change = not self.notify_on_change
            self._build_components()
            await interaction.response.edit_message(view=self)
            return False

        if custom_id == "toggle_cancel":
            self.notify_on_cancel = not self.notify_on_cancel
            self._build_components()
            await interaction.response.edit_message(view=self)
            return False

        if custom_id == "save":
            await self._save_preferences(interaction)
            return False

        if custom_id == "disable":
            await self._disable_notifications(interaction)
            return False

        return True

    async def _save_preferences(self, interaction: discord.Interaction):
        pref = notifications.NotificationPreference(
            user_id=self.user_id,
            guild_id=self.guild_id,
            event_name=self.event_name,
            reminder_minutes=self.reminder_minutes,
            notify_on_start=self.notify_on_start,
            notify_on_change=self.notify_on_change,
            notify_on_cancel=self.notify_on_cancel,
        )
        notifications.set_notification_preference(pref)

        reminder_label = next(
            (label for mins, label in REMINDER_OPTIONS if mins == self.reminder_minutes),
            f"{self.reminder_minutes} minutes before"
        )

        await interaction.response.edit_message(
            content=(
                f"✅ **Notifications enabled for {self.event_name}!**\n\n"
                f"⏰ Reminder: {reminder_label}\n"
                f"🎉 Event Start: {'✅' if self.notify_on_start else '❌'}\n"
                f"📝 Event Changes: {'✅' if self.notify_on_change else '❌'}\n"
                f"❌ Event Canceled: {'✅' if self.notify_on_cancel else '❌'}"
            ),
            view=None
        )
        self.stop()

    async def _disable_notifications(self, interaction: discord.Interaction):
        notifications.remove_notification_preference(
            self.user_id,
            self.guild_id,
            self.event_name
        )

        await interaction.response.edit_message(
            content=f"🔕 Notifications disabled for **{self.event_name}**.",
            view=None
        )
        self.stop()


class ToggleButton(Button):
    """A button that toggles between enabled/disabled states."""

    def __init__(self, label: str, enabled: bool, custom_id: str, row: int):
        emoji = "✅" if enabled else "❌"
        style = discord.ButtonStyle.success if enabled else discord.ButtonStyle.secondary

        super().__init__(
            label=f"{emoji} {label}",
            style=style,
            custom_id=custom_id,
            row=row
        )


# =============================================================================
# Command Handlers
# =============================================================================

async def show_notification_settings(
    interaction: discord.Interaction,
    event_name: str
):
    """
    Show notification settings for an event.

    Called from /remindme command or NotifyMe button.
    """
    guild_id = interaction.guild_id
    user_id = interaction.user.id

    # Verify event exists
    event_matches = events.get_events(guild_id, event_name)
    if not event_matches:
        await interaction.response.send_message(
            f"❌ Event `{event_name}` not found.",
            ephemeral=True
        )
        return

    if len(event_matches) > 1:
        # Multiple matches - show list
        event_list = "\n".join(f"• {name}" for name in event_matches.keys())
        await interaction.response.send_message(
            f"Multiple events match `{event_name}`:\n{event_list}\n\n"
            f"Please use the exact event name.",
            ephemeral=True
        )
        return

    # Get exact event name
    exact_name = list(event_matches.keys())[0]
    event = event_matches[exact_name]

    # Get current preference if exists
    current_pref = notifications.get_event_preference(user_id, guild_id, exact_name)

    view = NotificationSettingsView(
        user_id=user_id,
        guild_id=guild_id,
        event_name=exact_name,
        current_pref=current_pref
    )

    status = "enabled" if current_pref else "not set up"

    await interaction.response.send_message(
        f"🔔 **Notification Settings for {exact_name}**\n\n"
        f"Current status: {status}\n\n"
        f"Configure when you want to be notified:",
        view=view,
        ephemeral=True
    )


async def quick_enable_notifications(
    interaction: discord.Interaction,
    event_name: str
):
    """
    Quickly enable default notifications for an event.

    Called from bulletin NotifyMe button for fast signup.
    Opens the notification config view immediately on first click.
    """
    guild_id = interaction.guild_id
    user_id = interaction.user.id

    # Check if already enabled
    current_pref = notifications.get_event_preference(user_id, guild_id, event_name)

    if current_pref:
        # Already enabled - show settings to modify
        await show_notification_settings(interaction, event_name)
        return

    # First click - immediately open the config view (don't auto-enable)
    # This allows users to configure their preferences right away
    await show_notification_settings(interaction, event_name)
