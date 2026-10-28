"""Configuration and SQLite guild models for the Soundboard service."""
from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, List, Optional

from core.config import BaseConfigModel, BaseGuildConfig


@dataclass
class SoundsConfig(BaseConfigModel):
    """Typed model representing `config/sounds.json`."""

    enabled: bool
    volume: int
    volume_min: int
    volume_max: int
    volume_float_min: float
    volume_float_max: float
    volume_float_fallback: float
    sounds_dir: str
    voice_connect_timeout: float
    supported_extensions: List[str]
    max_file_size_bytes: int
    max_name_length: int
    max_autocomplete_choices: int
    max_sounds_per_page: int
    sound_name_pattern: str


@dataclass
class SoundsGuildConfig(BaseGuildConfig):
    """Per-guild SQLite configuration model for Soundboard (`sounds_config` table)."""

    table_name: ClassVar[str] = "sounds_config"

    guild_id: int
    volume: Optional[int] = None

