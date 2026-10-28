"""Configuration and SQLite guild models for the Text-to-Speech (TTS) service."""
from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, List, Optional

from core.config import BaseConfigModel, BaseGuildConfig


@dataclass
class TTSConfig(BaseConfigModel):
    """Typed model representing `config/tts.json`."""

    enabled: bool
    volume: int
    volume_min: int
    volume_max: int
    volume_float_min: float
    volume_float_max: float
    volume_float_fallback: float
    voice: str
    voice_speed: float
    voice_speed_min: float
    voice_speed_max: float
    intro_sound: str
    intro_delay: float
    intro_delay_min: float
    intro_delay_max: float
    max_text_length: int
    max_text_length_min: int
    max_text_length_max: int
    sounds_dir: str
    filter_urls: bool
    read_bot_messages: bool
    voice_connect_timeout: float
    temp_dir: str
    rate: str
    pitch: str
    synth_volume: str
    delay_seconds: float
    sample_rate: int
    max_autocomplete_choices: int
    max_title_preview_length: int
    disconnect_cleanup_delay: float
    default_locale_filter: str
    supported_extensions: List[str]
    mix_intro_volume: float
    mix_speech_volume: float
    mix_limiter_limit: float
    popular_voices: List[List[str]]
    speed_choices: List[List[str]]
    delay_choices: List[List[str]]


@dataclass
class TTSGuildConfig(BaseGuildConfig):
    """Per-guild SQLite configuration model for TTS (`tts_config` table)."""

    table_name: ClassVar[str] = "tts_config"

    guild_id: int
    voice: Optional[str] = None
    voice_speed: Optional[float] = None
    volume: Optional[int] = None
    max_text_length: Optional[int] = None
    intro_sound: Optional[str] = None
    intro_delay: Optional[float] = None
    bound_channel_id: Optional[int] = None

