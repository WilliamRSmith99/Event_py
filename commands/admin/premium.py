"""
Premium subscription commands and UI.

Provides information about premium features and upgrade options.
"""
import discord
from discord.ui import View, Button
from typing import Optional

from core import entitlements, stripe_integration
from core.entitlements import Feature, SubscriptionTier
from core.stripe_integration import SubscriptionPlan
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
            description="Thank you for supporting Overlap!",
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

    embed.set_footer(text="Overlap — schedule together, without the back-and-forth")
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

        return True

    async def _handle_subscribe(self, interaction: discord.Interaction, plan: str):
        """Handle subscription button click."""
        # Check if Stripe is configured
        if not stripe_integration.is_stripe_configured():
            await interaction.response.send_message(
                "🚧 **Coming Soon!**\n\n"
                "Online payments are being set up. "
                "Contact the bot developer to enable Premium for your server.",
                ephemeral=True
            )
            return

        # Determine plan
        subscription_plan = (
            SubscriptionPlan.YEARLY if plan == "yearly"
            else SubscriptionPlan.MONTHLY
        )

        # Create checkout session
        checkout_url = stripe_integration.create_checkout_session(
            guild_id=interaction.guild_id,
            guild_name=interaction.guild.name,
            plan=subscription_plan
        )

        if checkout_url:
            # Create a view with a URL button for better UX
            view = View(timeout=300)
            view.add_item(Button(
                label=f"Complete {plan.title()} Subscription",
                style=discord.ButtonStyle.link,
                url=checkout_url,
                emoji="💳"
            ))

            await interaction.response.send_message(
                f"💳 **Ready to Subscribe!**\n\n"
                f"Click the button below to complete your **{plan}** subscription.\n\n"
                f"*This link expires in 24 hours.*",
                view=view,
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "❌ **Error**\n\n"
                "Failed to create checkout session. Please try again later.",
                ephemeral=True
            )

    async def _handle_manage(self, interaction: discord.Interaction):
        """Handle manage subscription button click."""
        # Check if Stripe is configured
        if not stripe_integration.is_stripe_configured():
            await interaction.response.send_message(
                "🚧 **Coming Soon!**\n\n"
                "Subscription management portal is being set up.",
                ephemeral=True
            )
            return

        # Create portal session
        portal_url = stripe_integration.create_portal_session(interaction.guild_id)

        if portal_url:
            # Create a view with a URL button for better UX
            view = View(timeout=300)
            view.add_item(Button(
                label="Open Management Portal",
                style=discord.ButtonStyle.link,
                url=portal_url,
                emoji="⚙️"
            ))

            await interaction.response.send_message(
                f"⚙️ **Manage Your Subscription**\n\n"
                f"Update payment methods, view invoices, or cancel anytime.",
                view=view,
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "❌ **Error**\n\n"
                "Failed to create portal session. "
                "Make sure your server has an active subscription.",
                ephemeral=True
            )

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


class SubscriptionStatusView(View):
    """View for subscription status with contextual actions."""

    def __init__(self, guild_id: int, portal_url: Optional[str] = None):
        super().__init__(timeout=300)
        self.guild_id = guild_id

        is_premium = entitlements.is_premium(guild_id)

        if is_premium and portal_url:
            # Premium user: show manage button
            self.add_item(Button(
                label="Manage Subscription",
                style=discord.ButtonStyle.link,
                url=portal_url,
                emoji="⚙️"
            ))
        elif not is_premium:
            # Free user: show upgrade button
            self.add_item(Button(
                label="Upgrade to Premium",
                style=discord.ButtonStyle.primary,
                custom_id="show_upgrade_from_status",
                emoji="⭐"
            ))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        custom_id = interaction.data.get("custom_id", "")

        if custom_id == "show_upgrade_from_status":
            embed = create_premium_embed(self.guild_id)
            view = PremiumView(self.guild_id)
            await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
            return False

        return True


async def show_subscription_status(interaction: discord.Interaction):
    """Show current subscription status (admin only)."""
    guild_id = interaction.guild_id
    is_premium = entitlements.is_premium(guild_id)
    tier = entitlements.get_tier(guild_id)

    portal_url = None

    if is_premium:
        sub_info = entitlements.get_subscription_info(guild_id)
        expires_str = "Never" if not sub_info.expires_at else f"<t:{int(sub_info.expires_at.timestamp())}:F>"

        message = (
            f"✨ **Subscription Status**\n\n"
            f"Tier: **{tier.value.title()}**\n"
            f"Status: **Active** ✅\n"
            f"Renews: {expires_str}"
        )

        # Get portal URL if Stripe is configured
        if stripe_integration.is_stripe_configured():
            portal_url = stripe_integration.create_portal_session(guild_id)
    else:
        event_limit = entitlements.get_event_limit(guild_id)
        from core import events
        current_events = len(events.get_events(guild_id))

        message = (
            f"📋 **Subscription Status**\n\n"
            f"Tier: **Free**\n"
            f"Events: **{current_events}/{event_limit}**"
        )

    view = SubscriptionStatusView(guild_id, portal_url)
    await interaction.response.send_message(message, view=view, ephemeral=True)
