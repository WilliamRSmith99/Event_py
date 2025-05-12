# 🗓️ Discord Event Scheduler Bot

A Discord bot that allows users to **create**, **register**, **view**, and **manage events** within a server. Users can also set their timezones, get reminders, and track availability across members.

## 🚀 Features

- 🆕 Create new events with a slash command.
- 📋 Register your availability for any event.
- 🔎 View upcoming events or filter by name.
- 🗑️ Delete events with confirmation prompts.
- 🌍 Set and manage your timezone for accurate scheduling.
- 📊 View overlap and response summaries.
- 🔔 DM reminders for upcoming events.

## 🛠️ Commands

### 📆 Event Management

| Command | Description |
|--------|-------------|
| `/newevent` | Launch a modal to create a new event |
| `/events [event_name]` | View upcoming events (optionally filtered by name) |
| `/upcoming` | View all upcoming events |
| `/delete [event_name]` | Delete an existing event (with confirmation) |

### 👤 User Actions

| Command | Description |
|--------|-------------|
| `/register <event_name>` | Register your availability for an event |
| `/responses <event_name>` | View response and overlap summary for an event |
| `/remindme <event_name>` | Schedule a DM reminder for an event |
| `/timezone` | View or update your timezone setting |

## 🧠 How It Works

- Events are stored with proposed date and time options.
- Users register by selecting the time slots they’re available.
- Timezone is used to convert UTC to user-local time.
- The bot computes the best overlap between users for organizers.
- Safe UI interactions via Discord’s `discord.ui` views.
- Built-in confirmation steps for destructive actions like deletions.

## 📦 Project Structure

```
.
├── commands/
│   ├── create_event.py
│   ├── register.py
│   ├── view_responses.py
│   ├── event/
│   │   ├── info.py
│   │   ├── edit.py
│   │   ├── confirm.py
│   │   └── delete.py
│   └── timezone/
│       ├── timezone.py
│       └── TZ.json
├── database/
│   ├── events.py
│   ├── user_data.py
│   └── shared.py
├── bot.py
└── README.md
```

## ⚙️ Setup & Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/WilliamRSmith99/discord-event-bot.git
   cd discord-event-bot
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Environment Setup**
   Create a `.env` file or set the following environment variable:
   ```
   DISCORD_TOKEN=your_bot_token_here
   ```

4. **Run the bot**
   ```bash
   python bot.py
   ```

## ✅ Requirements

- Python 3.9+
- Discord.py 2.0+ (`py-cord` or official fork with slash command support)
- Permissions to create slash commands on your server
- Optional: dotenv for managing environment variables

## 🔐 Permissions Required

The bot requires the following permissions to function properly:
- Read Messages / Message History
- Send Messages / Embed Links
- Use Slash Commands
- Manage Messages (for editing/deleting ephemeral responses)

## 📎 Notes

- Max 25 options are shown due to Discord API limits (e.g., timezone selection).
- All operations like registration and timezone selection are ephemeral to preserve privacy.
- Responses are stored server-side (via the `database/` logic).

## 🤝 Contributing

Pull requests are welcome! For major changes, please open an issue first to discuss what you would like to change.

---

**Made with ❤️ for efficient community event coordination.**
