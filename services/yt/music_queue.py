from __future__ import annotations

from core.voice_queue import AudioTrack, GuildAudioPlayer
from services.yt.models import Song

# Backward compatibility alias for existing imports
GuildMusicPlayer = GuildAudioPlayer

__all__ = ["AudioTrack", "GuildAudioPlayer", "GuildMusicPlayer", "Song"]
