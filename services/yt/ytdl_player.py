from __future__ import annotations
import asyncio
from dataclasses import dataclass
import logging
from pathlib import Path
from typing import Any, Dict, Optional

import discord
import yt_dlp

logger = logging.getLogger("bot.service.yt.ytdl")

YTDL_OPTIONS: Dict[str, Any] = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
    "default_search": "ytsearch1",
    "source_address": "0.0.0.0",
    "extractor_args": {
        "youtube": {
            "player_client": ["android", "web", "mweb"],
        }
    },
}

FFMPEG_OPTIONS: Dict[str, str] = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn -loglevel fatal",
}

from services.yt.defaults import (
    DEFAULT_FFMPEG_PATH,
    DEFAULT_COOKIES_PATH,
    MIN_VOLUME_FLOAT,
    MAX_VOLUME_FLOAT,
)

DEFAULT_STREAM_VOLUME = 1.0


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


class YTDLExtractor:
    """Handles asynchronous extraction and preparation of YouTube audio streams."""

    def __init__(self, cookies_path: Optional[str] = DEFAULT_COOKIES_PATH) -> None:
        opts = dict(YTDL_OPTIONS)
        self.cookies_path = cookies_path or DEFAULT_COOKIES_PATH
        if self.cookies_path:
            cookie_file = Path(self.cookies_path)
            if cookie_file.is_file():
                opts["cookiefile"] = str(cookie_file.resolve())
                opts["extractor_args"] = {
                    "youtube": {
                        "player_client": ["web", "mweb", "android"],
                    }
                }
                logger.info("Using YouTube cookies from: %s", cookie_file)
            else:
                logger.warning("Configured cookies path '%s' not found. Continuing without cookies.", self.cookies_path)
        self.ydl = yt_dlp.YoutubeDL(opts)

    async def extract_song(
        self,
        query: str,
        requester: str,
        loop: Optional[asyncio.AbstractEventLoop] = None,
    ) -> Optional[Song]:
        """Extracts audio information for a URL or search query."""
        if loop is None:
            loop = asyncio.get_event_loop()

        clean_query = query.strip()
        if not (clean_query.startswith("http://") or clean_query.startswith("https://")):
            clean_query = f"ytsearch1:{clean_query}"

        try:
            data = await loop.run_in_executor(
                None, lambda: self.ydl.extract_info(clean_query, download=False)
            )
        except Exception as e:
            logger.error("Failed to extract info for query '%s': %s", query, e)
            return None

        if not data:
            return None

        # When searching with ytsearch, the result is wrapped inside 'entries'
        if "entries" in data:
            entries = data.get("entries")
            if not entries:
                return None
            data = entries[0]

        title = str(data.get("title", "Unknown Title"))
        webpage_url = str(data.get("webpage_url") or data.get("original_url") or query)
        stream_url = str(data.get("url", ""))
        duration = int(data.get("duration") or 0)
        thumbnail = data.get("thumbnail")
        uploader = str(data.get("uploader") or data.get("channel") or "Unknown Artist")

        if not stream_url:
            logger.error("No valid stream URL extracted for %s", webpage_url)
            return None

        return Song(
            title=title,
            webpage_url=webpage_url,
            stream_url=stream_url,
            duration=duration,
            thumbnail=thumbnail,
            uploader=uploader,
            requester=requester,
        )

    @staticmethod
    def create_audio_source(
        song: Song,
        volume: float = DEFAULT_STREAM_VOLUME,
        ffmpeg_path: str = DEFAULT_FFMPEG_PATH,
    ) -> discord.PCMVolumeTransformer:
        """Creates an FFmpeg audio source from direct stream URL with volume control."""
        source = discord.FFmpegPCMAudio(
            song.stream_url,
            executable=ffmpeg_path,
            before_options=FFMPEG_OPTIONS["before_options"],
            options=FFMPEG_OPTIONS["options"],
        )
        clamped_volume = max(MIN_VOLUME_FLOAT, min(volume, MAX_VOLUME_FLOAT))
        return discord.PCMVolumeTransformer(source, volume=clamped_volume)
