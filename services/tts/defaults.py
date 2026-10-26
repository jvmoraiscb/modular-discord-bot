from __future__ import annotations
from typing import Any, Dict, List, Tuple

DEFAULT_VOLUME = 100
DEFAULT_VOLUME_MIN = 1
DEFAULT_VOLUME_MAX = 100
DEFAULT_VOICE = "pt-BR-FranciscaNeural"
DEFAULT_VOICE_SPEED = 1.0
DEFAULT_VOICE_SPEED_MIN = 0.25
DEFAULT_VOICE_SPEED_MAX = 2.0
DEFAULT_INTRO_SOUND = "none"
DEFAULT_INTRO_DELAY = 1.0
DEFAULT_INTRO_DELAY_MIN = 0.0
DEFAULT_INTRO_DELAY_MAX = 5.0
DEFAULT_MAX_TEXT_LENGTH = 500
DEFAULT_MAX_TEXT_LENGTH_MIN = 10
DEFAULT_MAX_TEXT_LENGTH_MAX = 2000
DEFAULT_SOUNDS_DIR = "assets/sounds"
DEFAULT_FFMPEG_PATH = "ffmpeg"
DEFAULT_FILTER_URLS = True
DEFAULT_READ_BOT_MESSAGES = False
DEFAULT_VOICE_CONNECT_TIMEOUT = 15.0
DEFAULT_VOLUME_FLOAT_FALLBACK = 1.0
MIN_VOLUME_FLOAT = 0.0
MAX_VOLUME_FLOAT = 2.0
MAX_AUTOCOMPLETE_CHOICES = 25
MAX_TITLE_PREVIEW_LENGTH = 40
DEFAULT_PREFIX = "!"

# Synthesis engine defaults
DEFAULT_TEMP_DIR = "data/temp"
DEFAULT_RATE = "+0%"
DEFAULT_PITCH = "+0Hz"
DEFAULT_SYNTH_VOLUME = "+0%"
DEFAULT_DELAY_SECONDS = 0.5
DEFAULT_SAMPLE_RATE = 48000

POPULAR_VOICES: List[Tuple[str, str]] = [
    ("Jenny (en-US - Female)", "en-US-JennyNeural"),
    ("Guy (en-US - Male)", "en-US-GuyNeural"),
    ("Aria (en-US - Female)", "en-US-AriaNeural"),
    ("Francisca (pt-BR - Female)", "pt-BR-FranciscaNeural"),
    ("Antonio (pt-BR - Male)", "pt-BR-AntonioNeural"),
    ("Thalita (pt-BR - Multilingual)", "pt-BR-ThalitaMultilingualNeural"),
    ("Raquel (pt-PT - Female)", "pt-PT-RaquelNeural"),
    ("Duarte (pt-PT - Male)", "pt-PT-DuarteNeural"),
]

SPEED_CHOICES: List[Tuple[str, str]] = [
    ("0.5x (Slowest)", "0.5x"),
    ("0.6x", "0.6x"),
    ("0.7x", "0.7x"),
    ("0.8x (Slower)", "0.8x"),
    ("0.9x", "0.9x"),
    ("1.0x (Normal / Default)", "1.0x"),
    ("1.1x", "1.1x"),
    ("1.2x (Faster)", "1.2x"),
    ("1.3x", "1.3x"),
    ("1.4x", "1.4x"),
    ("1.5x (Fast)", "1.5x"),
    ("1.6x", "1.6x"),
    ("1.7x", "1.7x"),
    ("1.8x", "1.8x"),
    ("1.9x", "1.9x"),
    ("2.0x (Very Fast)", "2.0x"),
]

DELAY_CHOICES: List[Tuple[str, str]] = [
    ("0.0s (Simultaneous)", "0.0s"),
    ("0.2s", "0.2s"),
    ("0.3s", "0.3s"),
    ("0.4s", "0.4s"),
    ("0.5s", "0.5s"),
    ("0.6s", "0.6s"),
    ("0.7s", "0.7s"),
    ("0.8s", "0.8s"),
    ("1.0s (Default)", "1.0s"),
    ("1.2s", "1.2s"),
    ("1.5s", "1.5s"),
    ("2.0s", "2.0s"),
]

DEFAULT_TTS_CONFIG: Dict[str, Any] = {
    "enabled": True,
    "volume": DEFAULT_VOLUME,
    "volume_min": DEFAULT_VOLUME_MIN,
    "volume_max": DEFAULT_VOLUME_MAX,
    "voice": DEFAULT_VOICE,
    "voice_speed": DEFAULT_VOICE_SPEED,
    "voice_speed_min": DEFAULT_VOICE_SPEED_MIN,
    "voice_speed_max": DEFAULT_VOICE_SPEED_MAX,
    "intro_sound": DEFAULT_INTRO_SOUND,
    "intro_delay": DEFAULT_INTRO_DELAY,
    "intro_delay_min": DEFAULT_INTRO_DELAY_MIN,
    "intro_delay_max": DEFAULT_INTRO_DELAY_MAX,
    "max_text_length": DEFAULT_MAX_TEXT_LENGTH,
    "max_text_length_min": DEFAULT_MAX_TEXT_LENGTH_MIN,
    "max_text_length_max": DEFAULT_MAX_TEXT_LENGTH_MAX,
    "sounds_dir": DEFAULT_SOUNDS_DIR,
    "filter_urls": DEFAULT_FILTER_URLS,
    "read_bot_messages": DEFAULT_READ_BOT_MESSAGES,
    "ffmpeg_path": DEFAULT_FFMPEG_PATH,
}


def get_default_config() -> Dict[str, Any]:
    """Returns a copy of the default TTS service configuration."""
    return dict(DEFAULT_TTS_CONFIG)
