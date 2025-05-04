import json
from pathlib import Path

# File to store user timezone and schedule data
DATA_FILE = Path("database/USER_TIMEZONES.json")

# Load data on import
def load_user_timezones():
    if DATA_FILE.exists():
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return {}

# Save data to disk
def save_user_timezones(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

# The in-memory dictionary you’ll interact with
user_timezones = load_user_timezones()

# Convenience function to update a user's timezone
def set_user_timezone(user_id, timezone_str):
    user_id_str = str(user_id)
    if user_id_str not in user_timezones:
        user_timezones[user_id_str] = {"timezone": timezone_str}
    else:
        user_timezones[user_id_str]["timezone"] = timezone_str
    save_user_timezones(user_timezones)

# Get a user's timezone (or None if not set)
def get_user_timezone(user_id):
    return user_timezones.get(str(user_id), {}).get("timezone")