"""Centralized voice playback queue and state management."""
from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
import logging
from pathlib import Path
from typing import Deque, Optional, TYPE_CHECKING, Union

import discord

from core.ffmpeg import create_audio_source

if TYPE_CHECKING:
    from core.bot import ModularBot

logger = logging.getLogger("bot.core.voice_queue")


def format_duration(seconds: Optional[int]) -> str:
    """Formats duration in seconds to standard MM:SS or HH:MM:SS."""
    if not seconds or seconds <= 0:
        return "Live / Unknown"
    minutes, secs = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


@dataclass
class AudioTrack:
    """Represents a playable audio track with metadata and required playback parameters."""

    title: str
    source: Union[str, Path]
    volume: float
    volume_min: float
    volume_max: float
    service_name: Optional[str] = None
    requester: Optional[str] = None
    channel: Optional[discord.TextChannel] = None
    duration: Optional[int] = None
    thumbnail: Optional[str] = None
    uploader: Optional[str] = None
    webpage_url: Optional[str] = None
    text: Optional[str] = None
    is_temporary: bool = False
    before_options: Optional[str] = None
    options: Optional[str] = None

    @property
    def formatted_duration(self) -> str:
        return format_duration(self.duration)

    @property
    def is_stream(self) -> bool:
        return isinstance(self.source, str) and (
            self.source.startswith("http://") or self.source.startswith("https://")
        )


class GuildAudioPlayer:
    """Centralized audio queue and playback controller for a single guild."""

    def __init__(
        self,
        guild_id: int,
        bot: ModularBot,
    ) -> None:
        self.guild_id = guild_id
        self.bot = bot

        self.queue: Deque[AudioTrack] = deque()
        self.current_track: Optional[AudioTrack] = None
        self._idle_task: Optional[asyncio.Task] = None
        self._stopped = False

    @property
    def voice_client(self) -> Optional[discord.VoiceClient]:
        """Returns the active VoiceClient for this guild, if connected."""
        guild = self.bot.get_guild(self.guild_id)
        if guild and guild.voice_client:
            return guild.voice_client
        return None

    @property
    def idle_timeout(self) -> int:
        """Retrieves inactivity timeout in seconds from the bot configuration."""
        return self.bot.get_guild_timeout(self.guild_id)

    def is_playing(self) -> bool:
        """Returns True if audio is actively playing on the voice client."""
        vc = self.voice_client
        return bool(vc and vc.is_playing())

    def is_paused(self) -> bool:
        """Returns True if audio playback is currently paused."""
        vc = self.voice_client
        return bool(vc and vc.is_paused())

    async def add_track(self, track: AudioTrack) -> int:
        """Enqueues an audio track.

        Returns 0 if playback begins immediately, or the 1-based queue position.
        """
        self._cancel_idle_timer()
        self._stopped = False

        if self.current_track is None and not self.is_playing() and not self.is_paused():
            self.queue.append(track)
            await self.play_next()
            return 0

        self.queue.append(track)
        return len(self.queue)

    async def play_next(self) -> None:
        """Pops and plays the next audio track from the queue."""
        self._cancel_idle_timer()
        vc = self.voice_client

        if self.current_track:
            self._cleanup_track(self.current_track)
            self.current_track = None

        if not vc or not vc.is_connected():
            logger.warning("Voice client disconnected in guild %s. Clearing queue.", self.guild_id)
            self.stop()
            return

        if self._stopped:
            return

        if not self.queue:
            self.current_track = None
            self._start_idle_timer()
            return

        track = self.queue.popleft()
        self.current_track = track
        v_min = float(track.volume_min)
        v_max = float(track.volume_max)

        try:
            audio_source = create_audio_source(
                source=track.source,
                is_stream=track.is_stream,
                volume=track.volume,
                volume_min=v_min,
                volume_max=v_max,
                before_options=track.before_options,
                options=track.options,
            )

            vol = max(v_min, min(float(track.volume), v_max))

            def _after(error: Optional[Exception]) -> None:
                if error:
                    logger.error("Playback error in guild %s: %s", self.guild_id, error)
                asyncio.run_coroutine_threadsafe(self.play_next(), self.bot.loop)

            vc.play(audio_source, after=_after)
            logger.info(
                "Started playing '%s' (service: %s, volume: %.2f) in guild %s",
                track.title,
                track.service_name or "unknown",
                vol,
                self.guild_id,
            )
        except Exception as e:
            logger.exception("Failed to play track '%s' in guild %s: %s", track.title, self.guild_id, e)
            if track.channel:
                try:
                    await track.channel.send(f"Failed to play **{track.title}**: {e}")
                except Exception:
                    pass
            self._cleanup_track(track)
            self.current_track = None
            await self.play_next()

    def skip(self) -> bool:
        """Skips the currently playing track."""
        vc = self.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            vc.stop()
            return True
        return False

    def pause(self) -> bool:
        """Pauses audio playback."""
        vc = self.voice_client
        if vc and vc.is_playing():
            vc.pause()
            return True
        return False

    def resume(self) -> bool:
        """Resumes paused audio playback."""
        vc = self.voice_client
        if vc and vc.is_paused():
            vc.resume()
            return True
        return False

    def stop(self) -> None:
        """Flushes the queue, removes temporary files, and stops current playback."""
        self._stopped = True

        while self.queue:
            t = self.queue.popleft()
            self._cleanup_track(t)

        if self.current_track:
            self._cleanup_track(self.current_track)
            self.current_track = None

        vc = self.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            vc.stop()

        self._start_idle_timer()

    def set_current_volume(self, volume: float, volume_min: float, volume_max: float) -> None:
        """Dynamically adjusts playback volume for the active track."""
        vol = max(float(volume_min), min(float(volume), float(volume_max)))
        if self.current_track:
            self.current_track.volume = vol
        vc = self.voice_client
        if vc and vc.source and isinstance(vc.source, discord.PCMVolumeTransformer):
            vc.source.volume = vol

    def _start_idle_timer(self) -> None:
        """Starts the inactivity disconnect countdown if timeout > 0."""
        self._cancel_idle_timer()
        if self.idle_timeout > 0:
            self._idle_task = asyncio.create_task(self._disconnect_when_idle())

    def _cancel_idle_timer(self) -> None:
        """Cancels an active inactivity countdown."""
        if self._idle_task and not self._idle_task.done():
            self._idle_task.cancel()
            self._idle_task = None

    async def _disconnect_when_idle(self) -> None:
        """Disconnects the voice client after idle_timeout seconds of silence."""
        try:
            timeout = self.idle_timeout
            if timeout <= 0:
                return
            await asyncio.sleep(timeout)
            if self.idle_timeout <= 0:
                return
            vc = self.voice_client
            if vc and vc.is_connected() and not vc.is_playing() and not self.queue:
                logger.info(
                    "Inactivity timeout (%ds) reached in guild %s. Disconnecting voice client.",
                    timeout,
                    self.guild_id,
                )
                await vc.disconnect(force=True)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("Error during idle disconnect in guild %s: %s", self.guild_id, e)

    def _cleanup_track(self, track: AudioTrack) -> None:
        """Deletes temporary local audio files safely."""
        if not track.is_temporary:
            return
        try:
            p = Path(track.source)
            if p.exists():
                p.unlink(missing_ok=True)
        except Exception as e:
            logger.warning("Failed to delete temporary audio file %s: %s", track.source, e)
