from __future__ import annotations
from core.voice_queue import AudioTrack, GuildAudioPlayer

# Backward compatibility aliases for existing imports
QueueItem = AudioTrack
GuildVoicePlayer = GuildAudioPlayer

__all__ = ["AudioTrack", "GuildAudioPlayer", "QueueItem", "GuildVoicePlayer"]
