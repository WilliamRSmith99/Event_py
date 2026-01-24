import re
from typing import Union

def extract_event_name_from_bulletin(message_content: str) -> Union[str, None]:
    """
    Parses the event name from the bulletin message content using regex.
    Assumes the format: 📅 **Event:** `EVENT_NAME`
    """
    match = re.search(r"📅\s*\*\*Event:\*\*\s*`([^`]+)`", message_content)
    if match:
        return match.group(1)
    return None
