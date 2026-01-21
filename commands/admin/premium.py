"""
Premium subscription commands and UI.

Provides information about premium features and upgrade options.
"""
import discord
from discord.ui import View, Button
from typing import Optional

from core import entitlements
from core.entitlements import Feature, SubscriptionTier
from core.logging import get_logger
import config

logger = get_logger(__name__)


# =============================================================================
# Premium Info Embed
# =============================================================================

def create_premium_embed(guild_id: int) -> discord.Embed:
    """Create an embed showing premium features and current status."""
    is_premium = entitlements.is_premium(guild_id)
    tier = entitlements.get_tier(guild_id)

    if is_premium:
        embed = discord.Embed(
            title="✨ Premium Active",
            description="Thank you for supporting Event Bot!",
            color=discord.Color.gold()
        )
        embed.add_field(
            name="Your Benefits",
            value=(
                "✅ Unlimited events\n"
                "✅ Recurring events\n"
                "✅ Persistent availability memory\n"
                "✅ Advanced notifications\n"
                "✅ Priority support"
            ),
            inline=False
        )

        # Get subscription info
        sub_info = entitlements.get_subscription_info(guild_id)
        if sub_info.expires_at:
            expires_ts = f"<t:{int(sub_info.expires_at.timestamp())}:R>"
            embed.add_field(
                name="Subscription",
                value=f"Renews {expires_ts}",
                inline=False
            )
    else:
        embed = discord.Embed(
            title="⭐ Upgrade to Premium",
            description="Unlock powerful features for your community!",
            color=discord.Color.blue()
        )

        # Current limits
        event_limit = entitlements.get_event_limit(guild_id)
        embed.add_field(
            name="Free Tier",
            value=(
                f"📅 {event_limit} active events\n"
                "📋 Basic scheduling\n"
                "🔔 Basic notifications\n"
                "⏰ Timezone support"
            ),
            inline=True
        )

        embed.add_field(
            name="Premium Tier",
            value=(
                "📅 **Unlimited** events\n"
                "🔄 Recurring events\n"
                "🧠 Smart availability memory\n"
                "🔔 Advanced notifications\n"
                "⚡ Priority support"
            ),
            inline=True
        )

        embed.add_field(
            name="Pricing",
            value=(
                "**$5/month** or **$50/year** (save 17%)\n\n"
                "Cancel anytime. No questions asked."
            ),
            inline=False
        )

    embed.set_footer(text="Event Bot Premium")
    return embed


def create_feature_comparison_embed() -> discord.Embed:
    """Create a detailed feature comparison embed."""
    embed = discord.Embed(
        title="📊 Feature Comparison",
        color=discord.Color.blue()
    )

    features = [
        ("Active Events", "2", "Unlimited"),
        ("Basic Scheduling", "✅", "✅"),
        ("Timezone Support", "✅", "✅"),
        ("Public Bulletins", "✅", "✅"),
        ("Basic Notifications", "✅", "✅"),
        ("Recurring Events", "❌", "✅"),
        ("Availability Memory", "❌", "✅"),
        ("Advanced Notifications", "❌", "✅"),
        ("Priority Support", "❌", "✅"),
    ]

    free_col = []
    premium_col = []

    for feature, free_val, premium_val in features:
        free_col.append(f"{feature}: {free_val}")
        premium_col.append(f"{feature}: {premium_val}")

    embed.add_field(name="Free", value="\n".join(free_col), inline=True)
    embed.add_field(name="Premium", value="\n".join(premium_col), inline=True)

    return embed


# =============================================================================
# Premium View
# =============================================================================

class PremiumView(View):
    """View with premium upgrade buttons."""

    def __init__(self, guild_id: int):
        super().__init__(timeout=300)
        self.guild_id = guild_id

        is_premium = entitlements.is_premium(guild_id)

        if not is_premium:
            self.add_item(Button(
                label="Subscribe Monthly ($5/mo)",
                style=discord.ButtonStyle.primary,
                custom_id="subscribe_monthly",
                emoji="💳"
            ))
            self.add_item(Button(
                label="Subscribe Yearly ($50/yr)",
                style=discord.ButtonStyle.success,
                custom_id="subscribe_yearly",
                emoji="💎"
            ))
        else:
            self.add_item(Button(
                label="Manage Subscription",
                style=discord.ButtonStyle.secondary,
                custom_id="manage_subscription",
                emoji="⚙️"
            ))

        self.add_item(Button(
            label="Compare Features",
            style=discord.ButtonStyle.secondary,
            custom_id="compare_features",
            emoji="📊"
        ))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        custom_id = interaction.data.get("custom_id", "")

        if custom_id == "subscribe_monthly":
            await self._handle_subscribe(interaction, "monthly")
            return False

        if custom_id == "subscribe_yearly":
            await self._handle_subscribe(interaction, "yearly")
            return False

        if custom_id == "manage_subscription":
            await self._handle_manage(interaction)
            return False

        if custom_id == "compare_features":
            await self._handle_compare(interaction)
            return False

        return True

    async def _handle_subscribe(self, interaction: discord.Interaction, plan: str):
        """Handle subscription button click."""
        # In Phase 5, this will redirect to Stripe checkout
        # For now, show a placeholder message
        await interaction.response.send_message(
            f"🚧 **Coming Soon!**\n\n"
            f"Stripe checkout for the **{plan}** plan will be available soon.\n\n"
            f"For now, contact the bot developer to enable Premium for your server.",
            ephemeral=True
        )

    async def _handle_manage(self, interaction: discord.Interaction):
        """Handle manage subscription button click."""
        # In Phase 5, this will redirect to Stripe customer portal
        await interaction.response.send_message(
            "🚧 **Coming Soon!**\n\n"
            "Subscription management portal will be available soon.",
            ephemeral=True
        )

    async def _handle_compare(self, interaction: discord.Interaction):
        """Show feature comparison."""
        embed = create_feature_comparison_embed()
        await interaction.response.send_message(embed=embed, ephemeral=True)


# =============================================================================
# Command Handlers
# =============================================================================

async def show_upgrade_info(interaction: discord.Interaction):
    """Show premium upgrade information."""
    embed = create_premium_embed(interaction.guild_id)
    view = PremiumView(interaction.guild_id)

    await interaction.response.send_message(
        embed=embed,
        view=view,
        ephemeral=True
    )


async def show_subscription_status(interaction: discord.Interaction):
    """Show current subscription status (admin only)."""
    guild_id = interaction.guild_id
    is_premium = entitlements.is_premium(guild_id)
    tier = entitlements.get_tier(guild_id)

    if is_premium:
        sub_info = entitlements.get_subscription_info(guild_id)
        expires_str = "Never" if not sub_info.expires_at else f"<t:{int(sub_info.expires_at.timestamp())}:F>"

        message = (
            f"**Subscription Status**\n\n"
            f"Tier: **{tier.value.title()}**\n"
            f"Status: **Active** ✅\n"
            f"Expires: {expires_str}"
        )
    else:
        event_limit = entitlements.get_event_limit(guild_id)
        from core import events
        current_events = len(events.get_events(guild_id))

        message = (
            f"**Subscription Status**\n\n"
            f"Tier: **Free**\n"
            f"Events: **{current_events}/{event_limit}**\n\n"
            f"Use `/upgrade` to unlock unlimited events!"
        )

    await interaction.response.send_message(message, ephemeral=True)
