# Overlap

> Schedule together, without the back-and-forth.

A Discord bot for coordinating group events. Create events, propose times, collect availability, and find when everyone can meet.

## Features

### Core Scheduling
- **Create Events** - Launch a wizard to set up events with proposed dates and times
- **Smart Availability** - Users select times they're free, bot finds the overlap
- **Timezone Support** - All times shown in each user's local timezone
- **Public Bulletins** - Optionally post events to a channel for visibility

### Notifications
- **Customizable Reminders** - Get notified 15min, 1hr, or 1 day before events
- **Event Updates** - Notifications when events change or get canceled
- **Per-Event Settings** - Configure notifications for each event individually

### Premium Features
- **Unlimited Events** - Free tier: 2 active events, Premium: unlimited
- **Recurring Events** - Weekly, biweekly, monthly schedules
- **Availability Memory** - Bot learns your typical availability patterns
- **Priority Support** - Direct support channel access

## Commands

### Event Management

| Command | Description |
|---------|-------------|
| `/newevent` | Create a new event with date/time wizard |
| `/events [name]` | View all events or search by name |
| `/delete <name>` | Delete an event (organizer only) |

### User Actions

| Command | Description |
|---------|-------------|
| `/register <event>` | Select your available times for an event |
| `/responses <event>` | View availability overlap summary |
| `/remindme <event>` | Configure notification preferences |
| `/timezone` | Set your timezone for accurate scheduling |

### Admin

| Command | Description |
|---------|-------------|
| `/settings` | Configure bot settings for your server |
| `/upgrade` | View premium features and subscribe |
| `/subscription` | Check subscription status |

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure Environment

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

Required:
```env
DISCORD_TOKEN=your_discord_bot_token
```

Optional (for premium features):
```env
STRIPE_SECRET_KEY=sk_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_PRICE_MONTHLY=price_...
STRIPE_PRICE_YEARLY=price_...
```

### 3. Run the Bot

```bash
python bot.py
```

## Project Structure

```
overlap/
├── bot.py                    # Main entry point
├── config.py                 # Environment configuration
├── requirements.txt          # Python dependencies
│
├── commands/                 # Slash command handlers
│   ├── event/               # Event management (create, list, register)
│   ├── user/                # User commands (timezone, notifications)
│   ├── admin/               # Admin commands (settings, premium)
│   └── configs/             # Server configuration
│
├── core/                    # Business logic
│   ├── events.py           # Event state and operations
│   ├── userdata.py         # User timezone storage
│   ├── notifications.py    # Notification system
│   ├── entitlements.py     # Premium feature checks
│   ├── bulletins.py        # Public event announcements
│   ├── database.py         # SQLite database schema
│   ├── stripe_integration.py # Payment processing
│   └── repositories/       # Data access layer
│
├── web/                     # Web server for Stripe webhooks
│   ├── server.py           # FastAPI application
│   └── static/             # Checkout success/cancel pages
│
├── scripts/                 # Utility scripts
│   └── migrate_json_to_sqlite.py
│
└── docs/                    # Documentation
    └── STRIPE_SETUP.md     # Stripe configuration guide
```

## Configuration

### Server Settings

Admins can configure:
- **Roles & Permissions** - Who can create events, who can RSVP
- **Bulletin Channel** - Where to post public event announcements
- **Display Options** - Customize how events appear

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DISCORD_TOKEN` | Yes | Your Discord bot token |
| `ENV` | No | `development` or `production` |
| `DEV_GUILD_ID` | No | Restrict commands to one server (faster sync) |
| `DATA_DIR` | No | Where to store database (default: `./data`) |
| `LOG_LEVEL` | No | Logging verbosity (default: `INFO`) |

See `.env.example` for all options including Stripe configuration.

## Premium & Payments

Overlap uses Stripe for premium subscriptions. See [docs/STRIPE_SETUP.md](docs/STRIPE_SETUP.md) for setup instructions.

### Pricing
- **Monthly**: $5/month
- **Yearly**: $50/year (save 17%)

### Web Server

The bot includes a FastAPI server for Stripe webhooks. See [WEB_SERVER.md](WEB_SERVER.md) for details.

## Requirements

- Python 3.10+
- discord.py 2.3+
- SQLite (included with Python)
- FastAPI + Uvicorn (for premium features)
- Stripe account (for payments)

## Permissions

The bot needs these Discord permissions:
- Read Messages / View Channels
- Send Messages
- Embed Links
- Use Slash Commands
- Create Public Threads (for bulletins)
- Manage Threads (for bulletins)

## Development

### Database Migration

If migrating from JSON storage to SQLite:

```bash
python scripts/migrate_json_to_sqlite.py --dry-run  # Preview changes
python scripts/migrate_json_to_sqlite.py            # Run migration
```

### Running Tests

```bash
pytest tests/
```

## Contributing

Pull requests welcome! Please open an issue first for major changes.

## License

MIT

---

**Overlap** - Schedule together, without the back-and-forth.
