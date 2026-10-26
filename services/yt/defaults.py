from __future__ import annotations
from typing import Any, Dict

DEFAULT_VOLUME = 10
DEFAULT_VOLUME_MIN = 1
DEFAULT_VOLUME_MAX = 100
DEFAULT_VOICE_CONNECT_TIMEOUT = 15.0
DEFAULT_VOLUME_FLOAT_FALLBACK = 0.1
MIN_VOLUME_FLOAT = 0.0
MAX_VOLUME_FLOAT = 2.0
DEFAULT_FFMPEG_PATH = "ffmpeg"

DEFAULT_YT_CONFIG: Dict[str, Any] = {
    "enabled": True,
    "volume": DEFAULT_VOLUME,
    "volume_min": DEFAULT_VOLUME_MIN,
    "volume_max": DEFAULT_VOLUME_MAX,
    "ffmpeg_path": DEFAULT_FFMPEG_PATH,
}


def get_default_config() -> Dict[str, Any]:
    """Returns a copy of the default YouTube service configuration."""
    return dict(DEFAULT_YT_CONFIG)
