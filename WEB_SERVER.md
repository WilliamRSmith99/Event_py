# Web Server Quick Start

> **Overlap** — Schedule together, without the back-and-forth

Overlap includes a FastAPI web server for Stripe webhooks and checkout pages.

## Starting the Web Server

### Option 1: Automatic (with bot)

The web server starts automatically when you run the bot **if Stripe is configured**:

```bash
python bot.py
```

Check your logs for: `Web server started on 0.0.0.0:8080`

### Option 2: Standalone

Run the web server independently:

```bash
python -m web.server
```

## Accessing the Server

| Endpoint | URL | Description |
|----------|-----|-------------|
| Root | http://localhost:8080/ | API info |
| Health | http://localhost:8080/health | Health check |
| Stripe Health | http://localhost:8080/health/stripe | Stripe config status |
| Success Page | http://localhost:8080/success | Post-checkout success |
| Cancel Page | http://localhost:8080/cancel | Checkout cancelled |
| Webhook | http://localhost:8080/webhooks/stripe | Stripe webhook endpoint |

## Configuration

Set these in your `.env` file:

```env
# Web server
WEB_HOST=0.0.0.0
WEB_PORT=8080

# Required for web server to auto-start
STRIPE_SECRET_KEY=sk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_PRICE_MONTHLY=price_...
```

## Local Development with Stripe

Use Stripe CLI to forward webhooks to your local server:

```bash
# Install: https://stripe.com/docs/stripe-cli
stripe login
stripe listen --forward-to localhost:8080/webhooks/stripe
```

## Production

For production, the server needs HTTPS. Options:

1. **Reverse proxy** (nginx/Caddy) with SSL termination
2. **Cloud hosting** (Railway, Render, Fly.io)
3. **Cloudflare Tunnel** for the webhook endpoint

See [docs/STRIPE_SETUP.md](docs/STRIPE_SETUP.md) for full setup instructions.
