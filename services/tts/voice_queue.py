from __future__ import annotations
import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Dict, Optional

import discord

if TYPE_CHECKING:
    from core.bot import ModularBot

logger = logging.getLogger("bot.service.tts.voice_queue")


@dataclass
class QueueItem:
    file_path: Path
    text: str
    requester: str
    source_channel_id: Optional[int] = None
    is_temporary: bool = True


class GuildVoicePlayer:
    """Manages audio playback queue and voice connection lifecycle for a single guild."""

    def __init__(
        self,
        guild_id: int,
        bot: ModularBot,
        idle_timeout: int = 180,
        ffmpeg_path: str = "ffmpeg",
    ) -> None:
        self.guild_id = guild_id
        self.bot = bot
        self._idle_timeout = idle_timeout
        self.ffmpeg_path = ffmpeg_path

        self.queue: asyncio.Queue[QueueItem] = asyncio.Queue()
        self.current_item: Optional[QueueItem] = None
        self.worker_task: Optional[asyncio.Task] = None
        self.idle_task: Optional[asyncio.Task] = None
        self._playback_event = asyncio.Event()
        self._stopped = False

    @property
    def idle_timeout(self) -> int:
        """Dynamically retrieves inactivity timeout from bot configuration/overrides."""
        if hasattr(self.bot, "get_guild_timeout"):
            return self.bot.get_guild_timeout(self.guild_id)
        return self._idle_timeout

    @idle_timeout.setter
    def idle_timeout(self, value: int) -> None:
        self._idle_timeout = max(0, int(value))

    @property
    def voice_client(self) -> Optional[discord.VoiceClient]:
        guild = self.bot.get_guild(self.guild_id)
        if guild and guild.voice_client:
            return guild.voice_client
        return None

    def start_worker(self) -> None:
        """Starts queue consumer task if not currently running."""
        if self.worker_task is None or self.worker_task.done():
            self._stopped = False
            self.worker_task = asyncio.create_task(self._process_queue())

    async def add_item(self, item: QueueItem) -> int:
        """Enqueues an audio item and returns current queue position."""
        self._cancel_idle_timer()
        await self.queue.put(item)
        self.start_worker()
        return self.queue.qsize()

    async def _process_queue(self) -> None:
        """Sequential queue processing loop for voice playback."""
        while not self._stopped:
            try:
                # If queue is empty, start idle disconnect timer and wait for items
                if self.queue.empty():
                    self._start_idle_timer()
                    item = await self.queue.get()
                    self._cancel_idle_timer()
                else:
                    item = await self.queue.get()

                self.current_item = item
                vc = self.voice_client

                # If bot is no longer connected to voice, discard item
                if not vc or not vc.is_connected():
                    logger.warning("Bot disconnected from voice in guild %s. Discarding audio item.", self.guild_id)
                    self._cleanup_file(item.file_path, item.is_temporary)
                    self.current_item = None
                    self.queue.task_done()
                    break

                # Wait if voice client is still finishing prior playback
                while vc.is_playing() or vc.is_paused():
                    await asyncio.sleep(0.1)

                self._playback_event.clear()

                def after_playback(error: Optional[Exception]) -> None:
                    if error:
                        logger.error("Error during voice playback in guild %s: %s", self.guild_id, error)
                    self.bot.loop.call_soon_threadsafe(self._playback_event.set)

                # Initialize FFmpeg audio source
                audio_source = discord.FFmpegPCMAudio(
                    executable=self.ffmpeg_path,
                    source=str(item.file_path),
                    options="-loglevel error",
                )

                if not vc or not vc.is_connected():
                    logger.warning("Bot disconnected from voice in guild %s. Discarding audio item.", self.guild_id)
                    self._cleanup_file(item.file_path, item.is_temporary)
                    self.current_item = None
                    self.queue.task_done()
                    break

                try:
                    vc.play(audio_source, after=after_playback)
                    await self._playback_event.wait()
                except discord.ClientException as e:
                    logger.warning("Voice client unavailable for guild %s: %s", self.guild_id, e)

                # Cleanup temporary audio file after playback finishes
                self._cleanup_file(item.file_path, item.is_temporary)
                self.current_item = None
                self.queue.task_done()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception("Unexpected error in audio playback loop for guild %s: %s", self.guild_id, e)
                if self.current_item:
                    self._cleanup_file(self.current_item.file_path, self.current_item.is_temporary)
                    self.current_item = None

    def skip(self) -> bool:
        """Skips currently playing audio."""
        vc = self.voice_client
        if vc and vc.is_playing():
            vc.stop()
            return True
        return False

    async def stop(self) -> None:
        """Stops playback, empties queue, and cancels background tasks."""
        self._stopped = True
        vc = self.voice_client
        if vc and vc.is_playing():
            vc.stop()

        # Discard pending queue items and remove their files
        while not self.queue.empty():
            try:
                item = self.queue.get_nowait()
                self._cleanup_file(item.file_path, item.is_temporary)
                self.queue.task_done()
            except asyncio.QueueEmpty:
                break

        if self.current_item:
            self._cleanup_file(self.current_item.file_path, self.current_item.is_temporary)
            self.current_item = None

        if self.worker_task and not self.worker_task.done():
            self.worker_task.cancel()

        self._cancel_idle_timer()

    def _start_idle_timer(self) -> None:
        """Starts countdown timer for idle voice disconnection."""
        self._cancel_idle_timer()
        if self.idle_timeout > 0:
            self.idle_task = asyncio.create_task(self._disconnect_when_idle())

    def _cancel_idle_timer(self) -> None:
        """Cancels idle disconnect countdown timer."""
        if self.idle_task and not self.idle_task.done():
            self.idle_task.cancel()
            self.idle_task = None

    async def _disconnect_when_idle(self) -> None:
        """Disconnects voice client when idle past configured timeout threshold."""
        try:
            timeout = self.idle_timeout
            if timeout <= 0:
                return
            await asyncio.sleep(timeout)
            if self.idle_timeout <= 0:
                return
            vc = self.voice_client
            if vc and vc.is_connected() and not vc.is_playing() and self.queue.empty():
                logger.info("Disconnecting from voice in guild %s due to inactivity (%ds).", self.guild_id, timeout)
                await vc.disconnect()
        except asyncio.CancelledError:
            pass

    def _cleanup_file(self, file_path: Path, is_temporary: bool = True) -> None:
        """Safely removes temporary audio file from disk if marked as temporary."""
        if not is_temporary:
            return
        try:
            if file_path.exists():
                file_path.unlink(missing_ok=True)
        except Exception as e:
            logger.warning("Failed to delete temporary audio file %s: %s", file_path, e)

