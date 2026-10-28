"""Configuration, SQLite guild models, and media dataclasses for the YouTube service."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar, Dict, List, Optional

from core.config import BaseConfigModel, BaseGuildConfig
from core.voice_queue import format_duration


class DownloadTrimError(ValueError):
    """Raised when requested start/end trim timestamps are out of bounds."""
    pass


@dataclass
class YTConfig(BaseConfigModel):
    """Typed model representing `config/yt.json`."""

    enabled: bool
    volume: int
    volume_min: int
    volume_max: int
    volume_float_min: float
    volume_float_max: float
    volume_float_fallback: float
    voice_connect_timeout: float
    cookies_path: str
    temp_dir: str
    ytdl_format: str
    max_discord_upload_bytes: int
    download_video_format: str
    download_audio_format: str
    audio_postprocessor_codec: str
    audio_postprocessor_quality: str
    max_filename_length: int
    download_search_prefix: str
    video_merge_format: str
    min_start_time: int
    source_address: str
    player_clients: List[str]
    cookie_player_clients: List[str]
    remote_components: List[str]
    js_runtimes: Dict[str, Any]


@dataclass
class YTGuildConfig(BaseGuildConfig):
    """Per-guild SQLite configuration model for YouTube (`yt_config` table)."""

    table_name: ClassVar[str] = "yt_config"

    guild_id: int
    volume: Optional[int] = None


@dataclass
class Song:
    """Represents a playable YouTube track."""

    title: str
    webpage_url: str
    stream_url: str
    duration: int
    thumbnail: Optional[str]
    uploader: str
    requester: str

    @property
    def formatted_duration(self) -> str:
        return format_duration(self.duration)


@dataclass
class DownloadedMedia:
    """Represents a downloaded media file for Discord attachment."""

    file_path: Path
    title: str
    duration: int
    filesize: int
    uploader: str
    webpage_url: str
    is_audio: bool
    start_time: Optional[int] = None
    end_time: Optional[int] = None

    @property
    def filename(self) -> str:
        return self.file_path.name

    @property
    def formatted_duration(self) -> str:
        return format_duration(self.duration)

    @property
    def formatted_filesize(self) -> str:
        size_mb = self.filesize / (1024 * 1024)
        return f"{size_mb:.2f} MB"

    @property
    def formatted_filesize_mb(self) -> str:
        return self.formatted_filesize
