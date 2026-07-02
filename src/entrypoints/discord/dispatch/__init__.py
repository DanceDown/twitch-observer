"""Typed Discord dispatch helpers grouped by command domain."""

from .account import dispatch_start_account_link, dispatch_unlink_account
from .channel import dispatch_add_tracked_channel, dispatch_remove_tracked_channel, dispatch_set_tracked_channel_color
from .channel_events import (
    dispatch_add_channel_event,
    dispatch_remove_channel_event,
    dispatch_set_channel_event_color,
)
from .help import dispatch_help
from .patterns import (
    dispatch_add_pattern,
    dispatch_disable_pattern,
    dispatch_edit_pattern,
    dispatch_enable_pattern,
    dispatch_remove_pattern,
)
from .permissions import dispatch_clear_permissions, dispatch_grant_permissions, dispatch_revoke_permissions
from .replies import (
    dispatch_add_channel_event_reply,
    dispatch_add_pattern_reply,
    dispatch_disable_channel_event_reply,
    dispatch_disable_pattern_reply,
    dispatch_enable_channel_event_reply,
    dispatch_enable_pattern_reply,
    dispatch_remove_channel_event_reply,
    dispatch_remove_pattern_reply,
)
from .show import dispatch_show_configuration
from .thread import (
    dispatch_disable_thread,
    dispatch_enable_thread,
    dispatch_join_thread,
    dispatch_leave_thread,
    dispatch_set_thread_color,
    dispatch_set_thread_language,
)
from .ui_flow import dispatch_ui_flow_decision
from .user import dispatch_add_tracked_user, dispatch_remove_tracked_user
from .write import dispatch_send_twitch_message

__all__ = [
    "dispatch_add_channel_event",
    "dispatch_add_channel_event_reply",
    "dispatch_add_pattern",
    "dispatch_add_pattern_reply",
    "dispatch_add_tracked_channel",
    "dispatch_add_tracked_user",
    "dispatch_clear_permissions",
    "dispatch_disable_channel_event_reply",
    "dispatch_disable_pattern",
    "dispatch_disable_pattern_reply",
    "dispatch_disable_thread",
    "dispatch_help",
    "dispatch_edit_pattern",
    "dispatch_enable_channel_event_reply",
    "dispatch_enable_pattern",
    "dispatch_enable_pattern_reply",
    "dispatch_enable_thread",
    "dispatch_grant_permissions",
    "dispatch_join_thread",
    "dispatch_leave_thread",
    "dispatch_remove_channel_event",
    "dispatch_remove_channel_event_reply",
    "dispatch_remove_pattern",
    "dispatch_remove_pattern_reply",
    "dispatch_remove_tracked_channel",
    "dispatch_remove_tracked_user",
    "dispatch_revoke_permissions",
    "dispatch_send_twitch_message",
    "dispatch_set_channel_event_color",
    "dispatch_set_thread_color",
    "dispatch_set_thread_language",
    "dispatch_set_tracked_channel_color",
    "dispatch_show_configuration",
    "dispatch_start_account_link",
    "dispatch_ui_flow_decision",
    "dispatch_unlink_account",
]
