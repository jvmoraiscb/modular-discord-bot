from __future__ import annotations
from typing import Any, Dict, List, Tuple

DEFAULT_CONFIG_PATH = "config/bot.json"
DEFAULT_DB_PATH = "data/guild_settings.db"
DEFAULT_PREFIX = "!"
DEFAULT_DESCRIPTION = "Modular Discord Bot"
DEFAULT_FFMPEG_PATH = "ffmpeg"
DEFAULT_AUTO_DISCONNECT_TIMEOUT = 0
DEFAULT_TIMEOUT_MIN = 0
DEFAULT_TIMEOUT_MAX = 86400
DEFAULT_SYNC_COMMANDS = True
DEFAULT_STATUS_MESSAGE = "/bot help"
DEFAULT_VOICE_CONNECT_TIMEOUT = 15.0
MAX_QUEUE_DISPLAY = 10
MAX_AUTOCOMPLETE_CHOICES = 25

TIMEOUT_CHOICES: List[Tuple[str, int]] = [
    ("0s (Never disconnect)", 0),
    ("60s (1 minute)", 60),
    ("120s (2 minutes)", 120),
    ("180s (3 minutes)", 180),
    ("300s (5 minutes)", 300),
    ("600s (10 minutes)", 600),
]

DEFAULT_BOT_CONFIG: Dict[str, Any] = {
    "prefix": DEFAULT_PREFIX,
    "description": DEFAULT_DESCRIPTION,
    "sync_commands_on_startup": DEFAULT_SYNC_COMMANDS,
    "status_message": DEFAULT_STATUS_MESSAGE,
    "ffmpeg_path": DEFAULT_FFMPEG_PATH,
    "auto_disconnect_timeout_min": DEFAULT_TIMEOUT_MIN,
    "auto_disconnect_timeout_max": DEFAULT_TIMEOUT_MAX,
}


def get_default_config() -> Dict[str, Any]:
    """Returns a copy of the default bot core configuration."""
    return dict(DEFAULT_BOT_CONFIG)
