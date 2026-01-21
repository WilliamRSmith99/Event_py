"""
Stripe Integration for Event Bot.

Handles Stripe checkout sessions, customer management, and subscription
lifecycle for the premium tier.
"""
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Tuple
from enum import Enum

import config
from core.logging import get_logger
from core.repositories.subscriptions import SubscriptionRepository

logger = get_logger(__name__)

# Stripe SDK import (optional dependency)
try:
    import stripe
    stripe.api_key = config.STRIPE_SECRET_KEY
    STRIPE_AVAILABLE = bool(config.STRIPE_SECRET_KEY)
except ImportError:
    stripe = None
    STRIPE_AVAILABLE = False
    logger.warning("Stripe SDK not installed. Run: pip install stripe")


# =============================================================================
# Plan Configuration
# =============================================================================

class SubscriptionPlan(Enum):
    """Available subscription plans."""
    MONTHLY = "monthly"
    YEARLY = "yearly"


PLAN_CONFIG = {
    SubscriptionPlan.MONTHLY: {
        "name": "Premium Monthly",
        "price": 500,  # $5.00 in cents
        "interval": "month",
        "price_id": config.STRIPE_PRICE_MONTHLY,
    },
    SubscriptionPlan.YEARLY: {
        "name": "Premium Yearly",
        "price": 5000,  # $50.00 in cents
        "interval": "year",
        "price_id": config.STRIPE_PRICE_YEARLY,
    },
}


# =============================================================================
# Stripe Availability Check
# =============================================================================

def is_stripe_configured() -> bool:
    """Check if Stripe is properly configured."""
    return (
        STRIPE_AVAILABLE and
        config.STRIPE_SECRET_KEY and
        config.STRIPE_WEBHOOK_SECRET and
        (config.STRIPE_PRICE_MONTHLY or config.STRIPE_PRICE_YEARLY)
    )


def get_stripe_status() -> Dict[str, Any]:
    """Get detailed Stripe configuration status."""
    return {
        "sdk_installed": stripe is not None,
        "secret_key_set": bool(config.STRIPE_SECRET_KEY),
        "webhook_secret_set": bool(config.STRIPE_WEBHOOK_SECRET),
        "monthly_price_set": bool(config.STRIPE_PRICE_MONTHLY),
        "yearly_price_set": bool(config.STRIPE_PRICE_YEARLY),
        "configured": is_stripe_configured(),
    }


# =============================================================================
# Customer Management
# =============================================================================

def get_or_create_customer(
    guild_id: int,
    guild_name: str,
    email: Optional[str] = None
) -> Optional[str]:
    """
    Get existing Stripe customer or create a new one.

    Args:
        guild_id: Discord guild ID
        guild_name: Discord guild name for display
        email: Optional email for receipts

    Returns:
        Stripe customer ID or None on failure
    """
    if not is_stripe_configured():
        logger.warning("Stripe not configured, cannot create customer")
        return None

    # Check if guild already has a customer ID
    subscription = SubscriptionRepository.get_subscription(guild_id)
    if subscription.stripe_customer_id:
        return subscription.stripe_customer_id

    try:
        # Create new customer
        customer = stripe.Customer.create(
            name=guild_name,
            email=email,
            metadata={
                "guild_id": str(guild_id),
                "source": "event_bot"
            }
        )

        # Store customer ID
        SubscriptionRepository.update_stripe_ids(
            guild_id,
            customer_id=customer.id,
            subscription_id=None
        )

        logger.info(f"Created Stripe customer {customer.id} for guild {guild_id}")
        return customer.id

    except stripe.error.StripeError as e:
        logger.error(f"Failed to create Stripe customer: {e}")
        return None


# =============================================================================
# Checkout Session Creation
# =============================================================================

def create_checkout_session(
    guild_id: int,
    guild_name: str,
    plan: SubscriptionPlan,
    success_url: Optional[str] = None,
    cancel_url: Optional[str] = None
) -> Optional[str]:
    """
    Create a Stripe Checkout session for subscription.

    Args:
        guild_id: Discord guild ID
        guild_name: Discord guild name
        plan: Subscription plan (monthly or yearly)
        success_url: URL to redirect after successful payment
        cancel_url: URL to redirect if cancelled

    Returns:
        Checkout session URL or None on failure
    """
    if not is_stripe_configured():
        logger.warning("Stripe not configured, cannot create checkout")
        return None

    plan_config = PLAN_CONFIG.get(plan)
    if not plan_config or not plan_config["price_id"]:
        logger.error(f"No price ID configured for plan: {plan}")
        return None

    # Get or create customer
    customer_id = get_or_create_customer(guild_id, guild_name)

    try:
        session = stripe.checkout.Session.create(
            customer=customer_id,
            mode="subscription",
            line_items=[{
                "price": plan_config["price_id"],
                "quantity": 1,
            }],
            success_url=success_url or config.STRIPE_SUCCESS_URL,
            cancel_url=cancel_url or config.STRIPE_CANCEL_URL,
            metadata={
                "guild_id": str(guild_id),
                "plan": plan.value,
            },
            subscription_data={
                "metadata": {
                    "guild_id": str(guild_id),
                    "plan": plan.value,
                }
            }
        )

        logger.info(f"Created checkout session for guild {guild_id}, plan {plan.value}")
        return session.url

    except stripe.error.StripeError as e:
        logger.error(f"Failed to create checkout session: {e}")
        return None


def create_portal_session(guild_id: int) -> Optional[str]:
    """
    Create a Stripe Customer Portal session for subscription management.

    Args:
        guild_id: Discord guild ID

    Returns:
        Portal URL or None on failure
    """
    if not is_stripe_configured():
        logger.warning("Stripe not configured, cannot create portal")
        return None

    subscription = SubscriptionRepository.get_subscription(guild_id)
    if not subscription.stripe_customer_id:
        logger.warning(f"No Stripe customer for guild {guild_id}")
        return None

    try:
        session = stripe.billing_portal.Session.create(
            customer=subscription.stripe_customer_id,
            return_url=config.STRIPE_SUCCESS_URL
        )

        logger.info(f"Created portal session for guild {guild_id}")
        return session.url

    except stripe.error.StripeError as e:
        logger.error(f"Failed to create portal session: {e}")
        return None


# =============================================================================
# Webhook Event Handling
# =============================================================================

def verify_webhook_signature(payload: bytes, signature: str) -> Optional[Dict[str, Any]]:
    """
    Verify and parse a Stripe webhook event.

    Args:
        payload: Raw request body
        signature: Stripe-Signature header value

    Returns:
        Parsed event dict or None if verification fails
    """
    if not config.STRIPE_WEBHOOK_SECRET:
        logger.error("Webhook secret not configured")
        return None

    try:
        event = stripe.Webhook.construct_event(
            payload,
            signature,
            config.STRIPE_WEBHOOK_SECRET
        )
        return event

    except stripe.error.SignatureVerificationError as e:
        logger.error(f"Webhook signature verification failed: {e}")
        return None
    except ValueError as e:
        logger.error(f"Invalid webhook payload: {e}")
        return None


def handle_checkout_completed(event: Dict[str, Any]) -> bool:
    """
    Handle checkout.session.completed webhook event.

    Args:
        event: Stripe webhook event

    Returns:
        True if handled successfully
    """
    session = event["data"]["object"]
    guild_id = session.get("metadata", {}).get("guild_id")
    subscription_id = session.get("subscription")

    if not guild_id:
        logger.error("No guild_id in checkout session metadata")
        return False

    guild_id = int(guild_id)

    # Get subscription details from Stripe
    try:
        subscription = stripe.Subscription.retrieve(subscription_id)
        current_period_end = datetime.fromtimestamp(subscription.current_period_end)

        # Activate premium
        SubscriptionRepository.activate_premium(
            guild_id=guild_id,
            expires_at=current_period_end,
            stripe_customer_id=session.get("customer"),
            stripe_subscription_id=subscription_id
        )

        logger.info(f"Activated premium for guild {guild_id} until {current_period_end}")
        return True

    except stripe.error.StripeError as e:
        logger.error(f"Failed to process checkout completion: {e}")
        return False


def handle_subscription_updated(event: Dict[str, Any]) -> bool:
    """
    Handle customer.subscription.updated webhook event.

    Args:
        event: Stripe webhook event

    Returns:
        True if handled successfully
    """
    subscription = event["data"]["object"]
    guild_id = subscription.get("metadata", {}).get("guild_id")

    if not guild_id:
        # Try to find by subscription ID
        sub_info = SubscriptionRepository.get_by_stripe_subscription(subscription["id"])
        if sub_info:
            guild_id = sub_info.guild_id
        else:
            logger.error("Cannot find guild for subscription update")
            return False

    guild_id = int(guild_id)

    # Update expiration date
    current_period_end = datetime.fromtimestamp(subscription["current_period_end"])

    if subscription["status"] == "active":
        SubscriptionRepository.extend_subscription(guild_id, current_period_end)
        logger.info(f"Extended subscription for guild {guild_id} until {current_period_end}")
    elif subscription["status"] in ("canceled", "unpaid", "past_due"):
        SubscriptionRepository.deactivate_premium(guild_id)
        logger.info(f"Deactivated premium for guild {guild_id} due to status: {subscription['status']}")

    return True


def handle_subscription_deleted(event: Dict[str, Any]) -> bool:
    """
    Handle customer.subscription.deleted webhook event.

    Args:
        event: Stripe webhook event

    Returns:
        True if handled successfully
    """
    subscription = event["data"]["object"]
    guild_id = subscription.get("metadata", {}).get("guild_id")

    if not guild_id:
        # Try to find by subscription ID
        sub_info = SubscriptionRepository.get_by_stripe_subscription(subscription["id"])
        if sub_info:
            guild_id = sub_info.guild_id
        else:
            logger.error("Cannot find guild for subscription deletion")
            return False

    guild_id = int(guild_id)

    # Deactivate premium
    SubscriptionRepository.deactivate_premium(guild_id)
    logger.info(f"Deactivated premium for guild {guild_id} due to subscription deletion")

    return True


def handle_invoice_paid(event: Dict[str, Any]) -> bool:
    """
    Handle invoice.paid webhook event (for renewal).

    Args:
        event: Stripe webhook event

    Returns:
        True if handled successfully
    """
    invoice = event["data"]["object"]
    subscription_id = invoice.get("subscription")

    if not subscription_id:
        return True  # Not a subscription invoice

    # Get subscription to find guild
    sub_info = SubscriptionRepository.get_by_stripe_subscription(subscription_id)
    if not sub_info:
        logger.warning(f"Cannot find subscription for invoice: {subscription_id}")
        return True

    try:
        subscription = stripe.Subscription.retrieve(subscription_id)
        current_period_end = datetime.fromtimestamp(subscription.current_period_end)

        SubscriptionRepository.extend_subscription(sub_info.guild_id, current_period_end)
        logger.info(f"Renewed subscription for guild {sub_info.guild_id} until {current_period_end}")

    except stripe.error.StripeError as e:
        logger.error(f"Failed to process invoice payment: {e}")

    return True


def handle_invoice_payment_failed(event: Dict[str, Any]) -> bool:
    """
    Handle invoice.payment_failed webhook event.

    Args:
        event: Stripe webhook event

    Returns:
        True if handled successfully
    """
    invoice = event["data"]["object"]
    subscription_id = invoice.get("subscription")

    if not subscription_id:
        return True

    sub_info = SubscriptionRepository.get_by_stripe_subscription(subscription_id)
    if sub_info:
        logger.warning(f"Payment failed for guild {sub_info.guild_id}")
        # Don't immediately deactivate - Stripe will retry

    return True


# =============================================================================
# Main Webhook Handler
# =============================================================================

WEBHOOK_HANDLERS = {
    "checkout.session.completed": handle_checkout_completed,
    "customer.subscription.updated": handle_subscription_updated,
    "customer.subscription.deleted": handle_subscription_deleted,
    "invoice.paid": handle_invoice_paid,
    "invoice.payment_failed": handle_invoice_payment_failed,
}


def process_webhook(payload: bytes, signature: str) -> Tuple[bool, str]:
    """
    Process an incoming Stripe webhook.

    Args:
        payload: Raw request body
        signature: Stripe-Signature header

    Returns:
        Tuple of (success, message)
    """
    event = verify_webhook_signature(payload, signature)
    if not event:
        return False, "Invalid signature"

    event_type = event.get("type")
    logger.info(f"Processing webhook: {event_type}")

    handler = WEBHOOK_HANDLERS.get(event_type)
    if handler:
        try:
            success = handler(event)
            return success, f"Processed {event_type}"
        except Exception as e:
            logger.error(f"Error processing webhook {event_type}: {e}")
            return False, f"Error: {e}"
    else:
        logger.debug(f"Unhandled webhook type: {event_type}")
        return True, f"Ignored {event_type}"
