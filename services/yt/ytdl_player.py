"""YouTube audio and video player and extractor using yt-dlp and core.ffmpeg."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
import re
import time
from typing import Any, Dict, Optional

import discord
import yt_dlp

from core.ffmpeg import create_audio_source as core_create_audio_source, get_ffmpeg_path
from core.voice_queue import format_duration
from services.yt.models import DownloadedMedia, Song, YTConfig

logger = logging.getLogger("bot.service.yt.ytdl")


def sanitize_filename(name: str, max_length: int) -> str:
    """Removes invalid filename characters and limits length."""
    clean = re.sub(r'[\\/*?:"<>|]', "", name).strip()
    clean = re.sub(r"\s+", " ", clean)
    if not clean:
        clean = "media"
    return clean[:max_length]


class YTDLExtractor:
    """Manages audio metadata extraction and stream URL resolution using yt-dlp."""

    def __init__(
        self,
        config: YTConfig,
        cookies_path: Optional[str] = None,
    ) -> None:
        self.config = config
        self.cookies_path = cookies_path or config.cookies_path

        opts: Dict[str, Any] = {
            "format": str(config.ytdl_format),
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "default_search": str(config.download_search_prefix),
            "source_address": str(config.source_address),
            "remote_components": list(config.remote_components),
            "js_runtimes": dict(config.js_runtimes),
            "extractor_args": {
                "youtube": {
                    "player_client": list(config.player_clients),
                }
            },
        }

        if self.cookies_path:
            cookie_file = Path(self.cookies_path)
            if cookie_file.is_file():
                opts["cookiefile"] = str(cookie_file.resolve())
                opts["extractor_args"] = {
                    "youtube": {
                        "player_client": list(config.cookie_player_clients),
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
        """Extracts audio stream information for a URL or search query."""
        if loop is None:
            loop = asyncio.get_event_loop()

        search_prefix = str(self.config.download_search_prefix)
        clean_query = query.strip()
        if not (clean_query.startswith("http://") or clean_query.startswith("https://")):
            clean_query = f"{search_prefix}:{clean_query}"

        try:
            data = await loop.run_in_executor(
                None, lambda: self.ydl.extract_info(clean_query, download=False)
            )
        except Exception as e:
            logger.error("Failed to extract info for query '%s': %s", query, e)
            return None

        if not data:
            return None

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

    async def download_media(
        self,
        query: str,
        output_dir: Path,
        audio_only: bool = False,
        loop: Optional[asyncio.AbstractEventLoop] = None,
    ) -> Optional[DownloadedMedia]:
        """Downloads a YouTube video or audio to the given output directory."""
        if loop is None:
            loop = asyncio.get_event_loop()

        search_prefix = str(self.config.download_search_prefix)
        clean_query = query.strip()
        if not (clean_query.startswith("http://") or clean_query.startswith("https://")):
            clean_query = f"{search_prefix}:{clean_query}"

        output_dir.mkdir(parents=True, exist_ok=True)
        unique_prefix = f"dl_{int(time.time() * 1000)}"
        outtmpl = str(output_dir / f"{unique_prefix}_%(id)s.%(ext)s")

        dl_opts: Dict[str, Any] = {
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "outtmpl": outtmpl,
            "ffmpeg_location": get_ffmpeg_path(),
            "source_address": str(self.config.source_address),
            "remote_components": list(self.config.remote_components),
            "js_runtimes": dict(self.config.js_runtimes),
            "extractor_args": {
                "youtube": {
                    "player_client": list(self.config.player_clients),
                }
            },
        }

        if self.cookies_path:
            cookie_file = Path(self.cookies_path)
            if cookie_file.is_file():
                dl_opts["cookiefile"] = str(cookie_file.resolve())
                dl_opts["extractor_args"] = {
                    "youtube": {
                        "player_client": list(self.config.cookie_player_clients),
                    }
                }

        audio_codec = str(self.config.audio_postprocessor_codec)
        audio_quality = str(self.config.audio_postprocessor_quality)
        video_merge = str(self.config.video_merge_format)

        if audio_only:
            dl_opts["format"] = str(self.config.download_audio_format)
            dl_opts["postprocessors"] = [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": audio_codec,
                "preferredquality": audio_quality,
            }]
        else:
            dl_opts["format"] = str(self.config.download_video_format)
            dl_opts["merge_output_format"] = video_merge

        def _do_download() -> Optional[DownloadedMedia]:
            ydl = yt_dlp.YoutubeDL(dl_opts)
            try:
                data = ydl.extract_info(clean_query, download=True)
            except Exception as e:
                logger.error("Download failed for query '%s': %s", query, e)
                if "cookiefile" in dl_opts:
                    logger.info("Retrying download without cookies for query '%s'", query)
                    fallback_opts = dict(dl_opts)
                    fallback_opts.pop("cookiefile", None)
                    fallback_ydl = yt_dlp.YoutubeDL(fallback_opts)
                    try:
                        data = fallback_ydl.extract_info(clean_query, download=True)
                    except Exception as fallback_e:
                        logger.error("Fallback download failed: %s", fallback_e)
                        return None
                else:
                    return None

            if not data:
                return None

            if "entries" in data:
                entries = data.get("entries")
                if not entries:
                    return None
                data = entries[0]

            title = str(data.get("title", "Unknown Title"))
            duration = int(data.get("duration") or 0)
            uploader = str(data.get("uploader") or data.get("channel") or "Unknown Channel")
            webpage_url = str(data.get("webpage_url") or data.get("original_url") or query)

            candidate = Path(ydl.prepare_filename(data))
            expected_file: Optional[Path] = None

            if audio_only:
                target_audio = candidate.with_suffix(f".{audio_codec}")
                if target_audio.exists():
                    expected_file = target_audio
            else:
                target_video = candidate.with_suffix(f".{video_merge}")
                if target_video.exists():
                    expected_file = target_video

            if not expected_file and candidate.exists():
                expected_file = candidate

            if not expected_file:
                matches = list(output_dir.glob(f"{unique_prefix}_*"))
                if matches:
                    expected_file = matches[0]

            if not expected_file or not expected_file.exists():
                logger.error("Downloaded file could not be found for %s", clean_query)
                return None

            return DownloadedMedia(
                file_path=expected_file,
                title=title,
                duration=duration,
                filesize=expected_file.stat().st_size,
                uploader=uploader,
                webpage_url=webpage_url,
                is_audio=audio_only,
            )

        try:
            return await loop.run_in_executor(None, _do_download)
        except Exception as exc:
            logger.error("Error during download executor: %s", exc)
            return None

    @staticmethod
    def create_audio_source(
        song: Song,
        volume: float,
        volume_float_min: float,
        volume_float_max: float,
    ) -> discord.AudioSource:
        """Creates an audio source using core.ffmpeg with volume control."""
        return core_create_audio_source(
            source=song.stream_url,
            is_stream=True,
            volume=volume,
            volume_min=volume_float_min,
            volume_max=volume_float_max,
        )
