"""
Authentication and authorization module.

DEPRECATED: This module is maintained for backward compatibility.
New code should import from core.permissions instead.
"""

# Re-export everything from permissions for backward compatibility
from core.permissions import (
    # New API
    PermissionLevel,
    get_user_permission_level,
    has_permission,
    check_event_permission,
    require_permission,

    # Legacy API (still works but deprecated)
    authenticate,
    confirm_action,
    ConfirmActionView,
)

__all__ = [
    "PermissionLevel",
    "get_user_permission_level",
    "has_permission",
    "check_event_permission",
    "require_permission",
    "authenticate",
    "confirm_action",
    "ConfirmActionView",
]
