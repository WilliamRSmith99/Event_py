from pathlib import Path
from core.storage import read_json, write_json_atomic


# File to store user timezone and schedule data
DATA_FILE_NAME = "user_timezones.json"

# The in-memory dictionary you’ll interact with
user_timezones = read_json(DATA_FILE_NAME)

# Convenience function to update a user's timezone
def set_user_timezone(user_id, timezone_str):
    user_id_str = str(user_id)
    if user_id_str not in user_timezones:
        user_timezones[user_id_str] = {"timezone": timezone_str}
    else:
        user_timezones[user_id_str]["timezone"] = timezone_str
    write_json_atomic(DATA_FILE_NAME, user_timezones)

# Get a user's timezone (or None if not set)
def get_user_timezone(user_id):
    return user_timezones.get(str(user_id), {}).get("timezone", False)