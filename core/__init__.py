from __future__ import annotations

from core.bot import ModularBot
from core.config import BaseConfigModel, BaseGuildConfig, BotConfig, BotGuildConfig
from core.ffmpeg import (
    configure_ffmpeg,
    create_audio_source,
    get_ffmpeg_path,
    mix_audio_with_intro,
    set_ffmpeg_path,
    trim_media_file,
    verify_ffmpeg,
)
from core.guild_persistence import GuildPersistence
from core.service_base import BaseService
from core.service_manager import ServiceManager
from core.voice_queue import AudioTrack, GuildAudioPlayer

__all__ = [
    "ModularBot",
    "BaseConfigModel",
    "BaseGuildConfig",
    "BotConfig",
    "BotGuildConfig",
    "BaseService",
    "ServiceManager",
    "GuildPersistence",
    "AudioTrack",
    "GuildAudioPlayer",
    "configure_ffmpeg",
    "create_audio_source",
    "mix_audio_with_intro",
    "trim_media_file",
    "get_ffmpeg_path",
    "set_ffmpeg_path",
    "verify_ffmpeg",
]
