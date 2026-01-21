# Stripe Integration Setup Guide

This guide walks you through setting up Stripe for Event Bot's premium subscriptions.

## Overview

Event Bot uses Stripe for:
- **Checkout Sessions**: One-time payment flow for new subscribers
- **Customer Portal**: Self-service subscription management
- **Webhooks**: Automatic subscription lifecycle updates

## Prerequisites

1. A Stripe account (sign up at https://stripe.com)
2. Event Bot deployed and running
3. A domain with HTTPS for webhooks (or ngrok for local testing)

## Step 1: Create Stripe Products & Prices

### In Stripe Dashboard

1. Go to **Products** > **Add product**

2. Create the product:
   - **Name**: Event Bot Premium
   - **Description**: Unlock unlimited events, recurring events, and more!

3. Add pricing:
   - Click **Add price**
   - **Monthly**: $5.00 USD, recurring monthly
   - Note the **Price ID** (starts with `price_`)

4. Add another price:
   - **Yearly**: $50.00 USD, recurring yearly
   - Note the **Price ID**

### Example Price IDs
```
Monthly: price_1ABC123abc456DEF
Yearly:  price_1XYZ789xyz012GHI
```

## Step 2: Configure Webhooks

### In Stripe Dashboard

1. Go to **Developers** > **Webhooks**

2. Click **Add endpoint**

3. Configure the endpoint:
   - **Endpoint URL**: `https://your-domain.com/webhooks/stripe`
   - **Events to send**:
     - `checkout.session.completed`
     - `customer.subscription.updated`
     - `customer.subscription.deleted`
     - `invoice.paid`
     - `invoice.payment_failed`

4. Click **Add endpoint**

5. Copy the **Signing secret** (starts with `whsec_`)

### For Local Development (ngrok)

```bash
# Install ngrok: https://ngrok.com/download
ngrok http 8080

# Use the HTTPS URL from ngrok output
# Example: https://abc123.ngrok.io/webhooks/stripe
```

## Step 3: Get API Keys

### In Stripe Dashboard

1. Go to **Developers** > **API keys**

2. Copy:
   - **Secret key** (starts with `sk_test_` or `sk_live_`)
   - **Publishable key** (starts with `pk_test_` or `pk_live_`)

### Test vs Live Mode

- Use **Test mode** keys during development
- Switch to **Live mode** when ready for production
- Toggle in the top-right of Stripe Dashboard

## Step 4: Configure Environment Variables

Add these to your `.env` file:

```env
# Stripe API Keys
STRIPE_SECRET_KEY=sk_test_your_secret_key
STRIPE_PUBLISHABLE_KEY=pk_test_your_publishable_key

# Webhook Secret (from Step 2)
STRIPE_WEBHOOK_SECRET=whsec_your_webhook_secret

# Price IDs (from Step 1)
STRIPE_PRICE_MONTHLY=price_monthly_id
STRIPE_PRICE_YEARLY=price_yearly_id

# Redirect URLs after checkout
STRIPE_SUCCESS_URL=https://your-domain.com/success
STRIPE_CANCEL_URL=https://your-domain.com/cancel

# Web server settings
WEB_HOST=0.0.0.0
WEB_PORT=8080
WEB_BASE_URL=https://your-domain.com
```

## Step 5: Deploy the Web Server

The web server must be accessible over HTTPS for Stripe webhooks.

### Option A: Cloudflare Pages/Workers

Deploy the static success/cancel pages to Cloudflare Pages:

1. Create a new Cloudflare Pages project
2. Upload the `web/static/` directory
3. Configure custom domain

For the webhook endpoint, use Cloudflare Workers or a separate server.

### Option B: VPS/Cloud Server

```bash
# Install dependencies
pip install -r requirements.txt

# Run the bot (includes web server)
python bot.py

# Or run web server standalone
python -m web.server
```

### Option C: Docker

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
EXPOSE 8080
CMD ["python", "bot.py"]
```

## Step 6: Configure Customer Portal

### In Stripe Dashboard

1. Go to **Settings** > **Billing** > **Customer portal**

2. Enable features:
   - Cancel subscriptions
   - Update payment methods
   - View invoices

3. Configure branding:
   - Business name: Your bot name
   - Logo, colors, etc.

4. Save changes

## Step 7: Test the Integration

### Test Checkout Flow

1. In Discord, run `/upgrade`
2. Click "Subscribe Monthly" or "Subscribe Yearly"
3. Use Stripe test card: `4242 4242 4242 4242`
4. Any future date, any CVC
5. Complete checkout
6. Verify premium is activated in bot

### Test Webhook Events

Use Stripe CLI for local testing:

```bash
# Install Stripe CLI
# https://stripe.com/docs/stripe-cli

# Login
stripe login

# Forward webhooks to local server
stripe listen --forward-to localhost:8080/webhooks/stripe

# Trigger test events
stripe trigger checkout.session.completed
stripe trigger customer.subscription.deleted
```

### Test Cards

| Card Number | Description |
|-------------|-------------|
| 4242424242424242 | Succeeds |
| 4000000000000002 | Declines |
| 4000002500003155 | Requires authentication |

## Troubleshooting

### Webhooks Not Received

1. Check webhook endpoint URL is correct
2. Verify HTTPS is working
3. Check Stripe webhook logs in Dashboard
4. Verify `STRIPE_WEBHOOK_SECRET` matches

### Signature Verification Failed

1. Ensure raw request body is used (not parsed JSON)
2. Verify webhook secret is correct
3. Check for proxy/load balancer issues modifying request

### Checkout Session Fails

1. Check `STRIPE_PRICE_MONTHLY`/`YEARLY` are set
2. Verify price IDs exist in your Stripe account
3. Check Stripe API logs for errors

### Premium Not Activating

1. Check bot logs for webhook processing
2. Verify database is initialized
3. Check guild_id is correctly stored in metadata

## Security Considerations

1. **Never commit API keys** - Use environment variables
2. **Verify webhook signatures** - Already implemented
3. **Use HTTPS** - Required for production webhooks
4. **Restrict API access** - Consider IP allowlisting

## Going Live

Before accepting real payments:

1. Switch to **Live mode** in Stripe Dashboard
2. Update all environment variables with live keys
3. Create live products/prices (or copy from test mode)
4. Update webhook endpoint with live signing secret
5. Test thoroughly with small real transactions
6. Enable fraud prevention in Stripe settings

## Support

- Stripe Documentation: https://stripe.com/docs
- Stripe Support: https://support.stripe.com
- Event Bot Issues: https://github.com/your-repo/issues
