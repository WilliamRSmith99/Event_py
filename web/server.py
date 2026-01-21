"""
Web Server for Event Bot.

FastAPI-based web server for:
- Stripe webhook handling
- Health checks
- Static pages (success/cancel)
- Optional: OAuth flows, admin dashboard

Run standalone:
    python -m web.server

Or integrate with bot:
    from web.server import start_web_server
    await start_web_server()
"""
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import config
from core.logging import get_logger
from core import stripe_integration

logger = get_logger(__name__)

# Static files directory
STATIC_DIR = Path(__file__).parent / "static"

# FastAPI import (optional dependency)
try:
    from fastapi import FastAPI, Request, HTTPException, Header
    from fastapi.responses import JSONResponse, HTMLResponse, FileResponse
    from fastapi.staticfiles import StaticFiles
    import uvicorn
    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False
    logger.warning("FastAPI not installed. Run: pip install fastapi uvicorn")


# =============================================================================
# Application Lifespan
# =============================================================================

@asynccontextmanager
async def lifespan(app):
    """Application startup and shutdown."""
    logger.info("Web server starting up...")
    yield
    logger.info("Web server shutting down...")


# =============================================================================
# Create Application
# =============================================================================

def create_app() -> Optional["FastAPI"]:
    """Create the FastAPI application."""
    if not FASTAPI_AVAILABLE:
        return None

    app = FastAPI(
        title="Overlap API",
        description="Schedule together, without the back-and-forth",
        version="1.0.0",
        lifespan=lifespan
    )

    # ==========================================================================
    # Health Endpoints
    # ==========================================================================

    @app.get("/health")
    async def health_check():
        """Basic health check endpoint."""
        return {
            "status": "healthy",
            "service": "overlap-api"
        }

    @app.get("/health/stripe")
    async def stripe_health():
        """Check Stripe configuration status."""
        status = stripe_integration.get_stripe_status()
        return {
            "status": "configured" if status["configured"] else "not_configured",
            "details": status
        }

    # ==========================================================================
    # Stripe Webhook Endpoint
    # ==========================================================================

    @app.post("/webhooks/stripe")
    async def stripe_webhook(
        request: Request,
        stripe_signature: str = Header(None, alias="Stripe-Signature")
    ):
        """
        Handle incoming Stripe webhooks.

        Stripe will call this endpoint for subscription events.
        """
        if not stripe_signature:
            logger.warning("Webhook received without signature")
            raise HTTPException(status_code=400, detail="Missing Stripe-Signature header")

        # Get raw body for signature verification
        payload = await request.body()

        # Process the webhook
        success, message = stripe_integration.process_webhook(payload, stripe_signature)

        if success:
            return {"status": "success", "message": message}
        else:
            logger.error(f"Webhook processing failed: {message}")
            raise HTTPException(status_code=400, detail=message)

    # ==========================================================================
    # Checkout Session Endpoints (for custom checkout flow)
    # ==========================================================================

    @app.post("/checkout/create")
    async def create_checkout(
        guild_id: int,
        guild_name: str,
        plan: str = "monthly"
    ):
        """
        Create a Stripe Checkout session.

        This endpoint can be called from Discord to generate a checkout URL.
        In practice, checkout URLs are usually generated directly in the bot.
        """
        if not stripe_integration.is_stripe_configured():
            raise HTTPException(
                status_code=503,
                detail="Stripe is not configured"
            )

        plan_enum = stripe_integration.SubscriptionPlan.MONTHLY
        if plan.lower() == "yearly":
            plan_enum = stripe_integration.SubscriptionPlan.YEARLY

        checkout_url = stripe_integration.create_checkout_session(
            guild_id=guild_id,
            guild_name=guild_name,
            plan=plan_enum
        )

        if checkout_url:
            return {"checkout_url": checkout_url}
        else:
            raise HTTPException(
                status_code=500,
                detail="Failed to create checkout session"
            )

    @app.post("/portal/create")
    async def create_portal(guild_id: int):
        """
        Create a Stripe Customer Portal session.

        For managing existing subscriptions.
        """
        if not stripe_integration.is_stripe_configured():
            raise HTTPException(
                status_code=503,
                detail="Stripe is not configured"
            )

        portal_url = stripe_integration.create_portal_session(guild_id)

        if portal_url:
            return {"portal_url": portal_url}
        else:
            raise HTTPException(
                status_code=400,
                detail="Failed to create portal session. Guild may not have a subscription."
            )

    # ==========================================================================
    # Static Pages (Checkout Success/Cancel)
    # ==========================================================================

    @app.get("/success")
    async def checkout_success():
        """Page shown after successful checkout."""
        success_file = STATIC_DIR / "success.html"
        if success_file.exists():
            return FileResponse(success_file, media_type="text/html")
        return HTMLResponse(
            "<h1>Payment Successful!</h1>"
            "<p>Thank you! Your premium subscription is now active.</p>"
            "<p><a href='https://discord.com/channels/@me'>Return to Discord</a></p>"
        )

    @app.get("/cancel")
    async def checkout_cancel():
        """Page shown when checkout is cancelled."""
        cancel_file = STATIC_DIR / "cancel.html"
        if cancel_file.exists():
            return FileResponse(cancel_file, media_type="text/html")
        return HTMLResponse(
            "<h1>Checkout Cancelled</h1>"
            "<p>No worries! You can upgrade anytime with /upgrade in Discord.</p>"
            "<p><a href='https://discord.com/channels/@me'>Return to Discord</a></p>"
        )

    # ==========================================================================
    # Info Endpoints
    # ==========================================================================

    @app.get("/")
    async def root():
        """Root endpoint with API information."""
        return {
            "name": "Overlap",
            "tagline": "Schedule together, without the back-and-forth",
            "version": "1.0.0",
            "endpoints": {
                "health": "/health",
                "stripe_health": "/health/stripe",
                "stripe_webhook": "/webhooks/stripe",
                "create_checkout": "/checkout/create",
                "create_portal": "/portal/create",
                "success": "/success",
                "cancel": "/cancel"
            }
        }

    # Mount static files if directory exists
    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    return app


# =============================================================================
# Server Runner
# =============================================================================

app = create_app()


async def start_web_server(
    host: str = None,
    port: int = None,
    log_level: str = "info"
) -> Optional[asyncio.Task]:
    """
    Start the web server as an async task.

    Args:
        host: Host to bind to (default from config)
        port: Port to bind to (default from config)
        log_level: Uvicorn log level

    Returns:
        The server task, or None if FastAPI is not available
    """
    if not FASTAPI_AVAILABLE or app is None:
        logger.warning("Cannot start web server: FastAPI not installed")
        return None

    host = host or config.WEB_HOST
    port = port or config.WEB_PORT

    config_obj = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level=log_level,
        access_log=True
    )
    server = uvicorn.Server(config_obj)

    logger.info(f"Starting web server on {host}:{port}")

    # Run in background
    task = asyncio.create_task(server.serve())
    return task


def run_server():
    """Run the web server standalone."""
    if not FASTAPI_AVAILABLE or app is None:
        print("Error: FastAPI is not installed.")
        print("Install with: pip install fastapi uvicorn")
        return

    uvicorn.run(
        "web.server:app",
        host=config.WEB_HOST,
        port=config.WEB_PORT,
        reload=config.ENV == "development",
        log_level="info"
    )


if __name__ == "__main__":
    run_server()
