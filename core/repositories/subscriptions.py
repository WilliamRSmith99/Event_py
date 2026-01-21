"""
Subscription Repository for Event Bot.

Handles all database operations for premium subscriptions.
"""
from datetime import datetime
from typing import Dict, List, Optional

from core.database import (
    get_cursor, transaction, execute_query, execute_one,
    execute_write, row_to_dict
)
from core.logging import get_logger
from core.entitlements import SubscriptionInfo, SubscriptionTier

logger = get_logger(__name__)


class SubscriptionRepository:
    """Repository for subscription data operations."""

    @staticmethod
    def get_subscription(guild_id: int) -> SubscriptionInfo:
        """
        Get subscription info for a guild.

        Returns free tier if no subscription exists.

        Args:
            guild_id: Discord guild ID

        Returns:
            SubscriptionInfo for the guild
        """
        row = execute_one(
            "SELECT * FROM subscriptions WHERE guild_id = ?",
            (str(guild_id),)
        )

        if row:
            return SubscriptionRepository._row_to_subscription(dict(row), guild_id)

        # Return free tier default
        return SubscriptionInfo(
            guild_id=guild_id,
            tier=SubscriptionTier.FREE
        )

    @staticmethod
    def get_all_subscriptions() -> Dict[int, SubscriptionInfo]:
        """
        Get all subscriptions.

        Returns:
            Dict mapping guild_id -> SubscriptionInfo
        """
        rows = execute_query("SELECT * FROM subscriptions")
        return {
            int(row["guild_id"]): SubscriptionRepository._row_to_subscription(
                dict(row), int(row["guild_id"])
            )
            for row in rows
        }

    @staticmethod
    def get_premium_guilds() -> List[int]:
        """
        Get all guild IDs with active premium subscriptions.

        Returns:
            List of guild IDs with premium
        """
        rows = execute_query(
            """
            SELECT guild_id FROM subscriptions
            WHERE tier = 'premium'
            AND (expires_at IS NULL OR expires_at > datetime('now'))
            """
        )
        return [int(row["guild_id"]) for row in rows]

    @staticmethod
    def get_expiring_subscriptions(within_days: int = 7) -> List[SubscriptionInfo]:
        """
        Get subscriptions expiring within a certain number of days.

        Args:
            within_days: Number of days to look ahead

        Returns:
            List of expiring subscriptions
        """
        rows = execute_query(
            """
            SELECT * FROM subscriptions
            WHERE tier = 'premium'
            AND expires_at IS NOT NULL
            AND expires_at <= datetime('now', '+' || ? || ' days')
            AND expires_at > datetime('now')
            """,
            (within_days,)
        )
        return [
            SubscriptionRepository._row_to_subscription(dict(row), int(row["guild_id"]))
            for row in rows
        ]

    @staticmethod
    def activate_premium(
        guild_id: int,
        expires_at: datetime,
        stripe_customer_id: Optional[str] = None,
        stripe_subscription_id: Optional[str] = None
    ) -> bool:
        """
        Activate premium for a guild.

        Args:
            guild_id: Discord guild ID
            expires_at: When the subscription expires
            stripe_customer_id: Stripe customer ID
            stripe_subscription_id: Stripe subscription ID

        Returns:
            True if activated successfully
        """
        try:
            execute_write(
                """
                INSERT INTO subscriptions (
                    guild_id, tier, expires_at, stripe_customer_id, stripe_subscription_id
                ) VALUES (?, 'premium', ?, ?, ?)
                ON CONFLICT(guild_id) DO UPDATE SET
                    tier = 'premium',
                    expires_at = excluded.expires_at,
                    stripe_customer_id = excluded.stripe_customer_id,
                    stripe_subscription_id = excluded.stripe_subscription_id,
                    updated_at = datetime('now')
                """,
                (
                    str(guild_id),
                    expires_at.isoformat(),
                    stripe_customer_id,
                    stripe_subscription_id
                )
            )
            logger.info(f"Premium activated for guild {guild_id} until {expires_at}")
            return True

        except Exception as e:
            logger.error(f"Failed to activate premium: {e}")
            return False

    @staticmethod
    def deactivate_premium(guild_id: int) -> bool:
        """
        Deactivate premium for a guild.

        Args:
            guild_id: Discord guild ID

        Returns:
            True if deactivated successfully
        """
        try:
            execute_write(
                """
                UPDATE subscriptions
                SET tier = 'free', expires_at = NULL, updated_at = datetime('now')
                WHERE guild_id = ?
                """,
                (str(guild_id),)
            )
            logger.info(f"Premium deactivated for guild {guild_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to deactivate premium: {e}")
            return False

    @staticmethod
    def extend_subscription(guild_id: int, new_expires_at: datetime) -> bool:
        """
        Extend a subscription's expiration date.

        Args:
            guild_id: Discord guild ID
            new_expires_at: New expiration datetime

        Returns:
            True if extended successfully
        """
        try:
            execute_write(
                """
                UPDATE subscriptions
                SET expires_at = ?, updated_at = datetime('now')
                WHERE guild_id = ?
                """,
                (new_expires_at.isoformat(), str(guild_id))
            )
            logger.info(f"Subscription extended for guild {guild_id} until {new_expires_at}")
            return True

        except Exception as e:
            logger.error(f"Failed to extend subscription: {e}")
            return False

    @staticmethod
    def get_by_stripe_customer(customer_id: str) -> Optional[SubscriptionInfo]:
        """
        Get subscription by Stripe customer ID.

        Args:
            customer_id: Stripe customer ID

        Returns:
            SubscriptionInfo or None
        """
        row = execute_one(
            "SELECT * FROM subscriptions WHERE stripe_customer_id = ?",
            (customer_id,)
        )

        if row:
            return SubscriptionRepository._row_to_subscription(dict(row), int(row["guild_id"]))
        return None

    @staticmethod
    def get_by_stripe_subscription(subscription_id: str) -> Optional[SubscriptionInfo]:
        """
        Get subscription by Stripe subscription ID.

        Args:
            subscription_id: Stripe subscription ID

        Returns:
            SubscriptionInfo or None
        """
        row = execute_one(
            "SELECT * FROM subscriptions WHERE stripe_subscription_id = ?",
            (subscription_id,)
        )

        if row:
            return SubscriptionRepository._row_to_subscription(dict(row), int(row["guild_id"]))
        return None

    @staticmethod
    def update_stripe_ids(
        guild_id: int,
        customer_id: Optional[str],
        subscription_id: Optional[str]
    ) -> bool:
        """
        Update Stripe IDs for a subscription.

        Args:
            guild_id: Discord guild ID
            customer_id: Stripe customer ID
            subscription_id: Stripe subscription ID

        Returns:
            True if updated successfully
        """
        try:
            execute_write(
                """
                UPDATE subscriptions
                SET stripe_customer_id = ?,
                    stripe_subscription_id = ?,
                    updated_at = datetime('now')
                WHERE guild_id = ?
                """,
                (customer_id, subscription_id, str(guild_id))
            )
            return True

        except Exception as e:
            logger.error(f"Failed to update Stripe IDs: {e}")
            return False

    @staticmethod
    def delete_subscription(guild_id: int) -> bool:
        """
        Delete a subscription record entirely.

        Args:
            guild_id: Discord guild ID

        Returns:
            True if deleted successfully
        """
        try:
            execute_write(
                "DELETE FROM subscriptions WHERE guild_id = ?",
                (str(guild_id),)
            )
            return True

        except Exception as e:
            logger.error(f"Failed to delete subscription: {e}")
            return False

    @staticmethod
    def _row_to_subscription(row: dict, guild_id: int) -> SubscriptionInfo:
        """Convert a database row to a SubscriptionInfo object."""
        expires_at = None
        if row.get("expires_at"):
            try:
                expires_at = datetime.fromisoformat(row["expires_at"])
            except ValueError:
                pass

        return SubscriptionInfo(
            guild_id=guild_id,
            tier=SubscriptionTier(row.get("tier", "free")),
            expires_at=expires_at,
            stripe_customer_id=row.get("stripe_customer_id"),
            stripe_subscription_id=row.get("stripe_subscription_id")
        )
