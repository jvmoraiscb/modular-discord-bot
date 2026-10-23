from __future__ import annotations
import asyncio
from collections import deque
import logging
from typing import Deque, Optional, TYPE_CHECKING

import discord

from services.yt.ytdl_player import Song, YTDLExtractor

if TYPE_CHECKING:
    from core.bot import ModularBot

logger = logging.getLogger("bot.service.yt.queue")


class GuildMusicPlayer:
    """Manages audio queue, playback lifecycle, and volume for a single server (guild)."""

    def __init__(
        self,
        guild: discord.Guild,
        bot: ModularBot,
        volume: float = 1.0,
        idle_timeout: int = 300,
        ffmpeg_path: str = "ffmpeg",
    ) -> None:
        self.guild = guild
        self.bot = bot
        self.queue: Deque[Song] = deque()
        self.current_song: Optional[Song] = None
        self.volume: float = volume
        self._idle_timeout = idle_timeout
        self.ffmpeg_path = ffmpeg_path
        self.last_channel: Optional[discord.abc.Messageable] = None
        self._idle_task: Optional[asyncio.Task] = None

    @property
    def idle_timeout(self) -> int:
        """Dynamically retrieves inactivity timeout from bot configuration/overrides."""
        if hasattr(self.bot, "get_guild_timeout"):
            return self.bot.get_guild_timeout(self.guild.id)
        return self._idle_timeout

    @idle_timeout.setter
    def idle_timeout(self, value: int) -> None:
        self._idle_timeout = max(0, int(value))

    @property
    def voice_client(self) -> Optional[discord.VoiceClient]:
        """Returns current discord.VoiceClient connected in this guild, if any."""
        return self.guild.voice_client

    def is_playing(self) -> bool:
        """Returns True if the voice client is actively playing audio."""
        vc = self.voice_client
        return bool(vc and vc.is_playing())

    def is_paused(self) -> bool:
        """Returns True if the voice client is currently paused."""
        vc = self.voice_client
        return bool(vc and vc.is_paused())

    async def add_song(self, song: Song, channel: Optional[discord.abc.Messageable] = None) -> int:
        """Adds a track to the guild music queue.

        Returns 0 if the track started playing immediately, or the 1-based queue position.
        """
        self._cancel_idle_timer()
        if channel:
            self.last_channel = channel

        if self.current_song is None:
            self.queue.append(song)
            vc = self.voice_client
            if vc and vc.is_playing():
                vc.stop()
            await self.play_next()
            return 0

        self.queue.append(song)
        return len(self.queue)

    async def play_next(self) -> None:
        """Retrieves and plays the next song from the queue."""
        self._cancel_idle_timer()
        vc = self.voice_client

        if not vc or not vc.is_connected():
            logger.warning("Voice client disconnected for guild %s. Clearing YouTube queue.", self.guild.id)
            self.stop()
            return

        if self.queue:
            song = self.queue.popleft()
            self.current_song = song

            try:
                source = YTDLExtractor.create_audio_source(
                    song=song,
                    volume=self.volume,
                    ffmpeg_path=self.ffmpeg_path,
                )
                vc.play(source, after=self._after_playback)
                logger.info("Started playing '%s' in guild %s", song.title, self.guild.id)
            except Exception as e:
                logger.exception("Failed to play '%s' in guild %s: %s", song.title, self.guild.id, e)
                if self.last_channel:
                    try:
                        await self.last_channel.send(f"Failed to play **{song.title}**: {e}")
                    except Exception:
                        pass
                await self.play_next()
        else:
            self.current_song = None
            self._start_idle_timer()

    def _after_playback(self, error: Optional[Exception]) -> None:
        """Callback invoked by discord.py once an audio track finishes."""
        if error:
            logger.error("Audio playback error in guild %s: %s", self.guild.id, error)
        # Schedule playing the next track in the bot's event loop
        asyncio.run_coroutine_threadsafe(self.play_next(), self.bot.loop)

    def skip(self) -> bool:
        """Skips the currently playing track."""
        vc = self.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            vc.stop()
            return True
        return False

    def pause(self) -> bool:
        """Pauses current audio playback."""
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
        """Stops playback and flushes the queue."""
        self.queue.clear()
        self.current_song = None
        vc = self.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            vc.stop()
        self._start_idle_timer()

    def set_volume(self, volume: float) -> None:
        """Sets playback volume (0.0 to 2.0)."""
        self.volume = max(0.0, min(volume, 2.0))
        vc = self.voice_client
        if vc and vc.source and isinstance(vc.source, discord.PCMVolumeTransformer):
            vc.source.volume = self.volume

    def _start_idle_timer(self) -> None:
        """Initiates inactivity countdown before leaving voice channel."""
        self._cancel_idle_timer()
        if self.idle_timeout > 0:
            self._idle_task = asyncio.create_task(self._idle_disconnect())

    def _cancel_idle_timer(self) -> None:
        """Cancels active inactivity countdown."""
        if self._idle_task and not self._idle_task.done():
            self._idle_task.cancel()
            self._idle_task = None

    async def _idle_disconnect(self) -> None:
        """Waits for configured inactivity timeout then disconnects voice client."""
        try:
            timeout = self.idle_timeout
            if timeout <= 0:
                return
            await asyncio.sleep(timeout)
            if self.idle_timeout <= 0:
                return
            vc = self.voice_client
            if vc and vc.is_connected() and not vc.is_playing() and not self.queue:
                logger.info("YouTube player idle timeout reached in guild %s. Disconnecting.", self.guild.id)
                await vc.disconnect()
                if self.last_channel:
                    try:
                        await self.last_channel.send(
                            "Left voice channel due to inactivity. Use `/yt play` to play music again!"
                        )
                    except Exception:
                        pass
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("Error during YouTube player idle disconnect: %s", e)
