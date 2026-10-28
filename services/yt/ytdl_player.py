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

from core.ffmpeg import (
    create_audio_source as core_create_audio_source,
    get_ffmpeg_path,
    trim_media_file,
)
from core.voice_queue import format_duration
from services.yt.models import DownloadedMedia, DownloadTrimError, Song, YTConfig

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

        logger.info("Extracting YouTube stream info for query '%s' (requester: %s)", query, requester)

        try:
            data = await loop.run_in_executor(
                None, lambda: self.ydl.extract_info(clean_query, download=False)
            )
        except Exception as e:
            logger.error("Failed to extract info for query '%s': %s", query, e)
            return None

        if not data:
            logger.warning("No metadata returned by yt-dlp for query '%s'", query)
            return None

        if "entries" in data:
            entries = data.get("entries")
            if not entries:
                logger.warning("No search entries found for query '%s'", query)
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

        logger.info(
            "Successfully extracted song '%s' (duration: %ds, url: %s)",
            title,
            duration,
            webpage_url,
        )

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
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
        loop: Optional[asyncio.AbstractEventLoop] = None,
    ) -> Optional[DownloadedMedia]:
        """Downloads a YouTube video or audio (with optional start_time and end_time cut) to output_dir."""
        if loop is None:
            loop = asyncio.get_event_loop()

        logger.info(
            "Starting media download for query '%s' (audio_only=%s, start_time=%s, end_time=%s)",
            query,
            audio_only,
            start_time,
            end_time,
        )

        min_start = int(self.config.min_start_time)
        if start_time is not None and start_time < min_start:
            logger.warning("Invalid start_time=%s (< %d) for query '%s'", start_time, min_start, query)
            raise DownloadTrimError(f"Start time cannot be less than {min_start} seconds.")

        if end_time is not None and end_time <= min_start:
            logger.warning("Invalid end_time=%s (<= %d) for query '%s'", end_time, min_start, query)
            raise DownloadTrimError(f"End time must be greater than {min_start} seconds.")

        if start_time is not None and end_time is not None and start_time >= end_time:
            logger.warning(
                "Invalid cut interval start_time=%s >= end_time=%s for query '%s'",
                start_time,
                end_time,
                query,
            )
            raise DownloadTrimError(
                f"Start time ({start_time}s) must be less than end time ({end_time}s)."
            )

        search_prefix = str(self.config.download_search_prefix)
        clean_query = query.strip()
        if not (clean_query.startswith("http://") or clean_query.startswith("https://")):
            clean_query = f"{search_prefix}:{clean_query}"

        output_dir.mkdir(parents=True, exist_ok=True)
        unique_prefix = f"dl_{int(time.time() * 1000)}"
        outtmpl = str(output_dir / f"{unique_prefix}_%(id)s.%(ext)s")
        ffmpeg_loc = get_ffmpeg_path()

        dl_opts: Dict[str, Any] = {
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "outtmpl": outtmpl,
            "ffmpeg_location": ffmpeg_loc,
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

        def _extract_with_fallback(ydl_opts: Dict[str, Any], download: bool) -> Optional[Dict[str, Any]]:
            ydl = yt_dlp.YoutubeDL(ydl_opts)
            try:
                return ydl.extract_info(clean_query, download=download)
            except Exception as e:
                logger.error("yt-dlp operation (download=%s) failed for query '%s': %s", download, query, e)
                if "cookiefile" in ydl_opts:
                    logger.info("Retrying without cookies for query '%s'", query)
                    fallback_opts = dict(ydl_opts)
                    fallback_opts.pop("cookiefile", None)
                    fallback_ydl = yt_dlp.YoutubeDL(fallback_opts)
                    try:
                        return fallback_ydl.extract_info(clean_query, download=download)
                    except Exception as fallback_e:
                        logger.error("Fallback failed: %s", fallback_e)
                        return None
                return None

        def _do_download() -> Optional[DownloadedMedia]:
            # First extract metadata without downloading to validate video duration against trim bounds
            logger.info("Fetching metadata to validate duration for query '%s'", query)
            info_data = _extract_with_fallback(dl_opts, download=False)
            if not info_data:
                logger.warning("Metadata extraction returned empty result for query '%s'", query)
                return None

            if "entries" in info_data:
                entries = info_data.get("entries")
                if not entries:
                    logger.warning("No search entries returned during metadata check for query '%s'", query)
                    return None
                info_data = entries[0]

            video_duration = int(info_data.get("duration") or 0)
            info_title = str(info_data.get("title", "Unknown Title"))
            logger.info(
                "Metadata resolved for '%s' (duration: %ds)",
                info_title,
                video_duration,
            )

            if start_time is not None and video_duration > 0 and start_time >= video_duration:
                logger.warning(
                    "Trim validation failed for '%s': start_time (%ds) >= video_duration (%ds)",
                    info_title,
                    start_time,
                    video_duration,
                )
                raise DownloadTrimError(
                    f"Start time ({start_time}s) must be less than the video duration ({video_duration}s / {format_duration(video_duration)})."
                )

            if end_time is not None and video_duration > 0 and end_time > video_duration:
                logger.warning(
                    "Trim validation failed for '%s': end_time (%ds) > video_duration (%ds)",
                    info_title,
                    end_time,
                    video_duration,
                )
                raise DownloadTrimError(
                    f"End time ({end_time}s) cannot exceed the video duration ({video_duration}s / {format_duration(video_duration)})."
                )

            logger.info(
                "Downloading media file for '%s' (format: %s, ffmpeg: %s)",
                info_title,
                audio_codec if audio_only else video_merge,
                ffmpeg_loc,
            )
            data = _extract_with_fallback(dl_opts, download=True)
            if not data:
                logger.error("Download step returned no data for query '%s'", query)
                return None

            if "entries" in data:
                entries = data.get("entries")
                if not entries:
                    logger.error("Download step returned empty entries for query '%s'", query)
                    return None
                data = entries[0]

            title = str(data.get("title", "Unknown Title"))
            duration = int(data.get("duration") or video_duration or 0)
            uploader = str(data.get("uploader") or data.get("channel") or "Unknown Channel")
            webpage_url = str(data.get("webpage_url") or data.get("original_url") or query)

            ydl = yt_dlp.YoutubeDL(dl_opts)
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

            effective_start = start_time if start_time is not None else min_start
            effective_end = end_time if end_time is not None else duration

            if start_time is not None or end_time is not None:
                logger.info(
                    "Trimming downloaded file '%s' from %ds to %ds",
                    expected_file.name,
                    effective_start,
                    effective_end,
                )
                trimmed_path = expected_file.with_name(
                    f"{expected_file.stem}_trim{expected_file.suffix}"
                )
                expected_file = trim_media_file(
                    input_path=expected_file,
                    output_path=trimmed_path,
                    start_seconds=effective_start,
                    end_seconds=effective_end,
                )
                duration = max(0, effective_end - effective_start)

            final_size = expected_file.stat().st_size
            logger.info(
                "Media download complete: '%s' -> %s (%d bytes, duration: %ds)",
                title,
                expected_file.name,
                final_size,
                duration,
            )

            return DownloadedMedia(
                file_path=expected_file,
                title=title,
                duration=duration,
                filesize=final_size,
                uploader=uploader,
                webpage_url=webpage_url,
                is_audio=audio_only,
                start_time=effective_start if (start_time is not None or end_time is not None) else None,
                end_time=effective_end if (start_time is not None or end_time is not None) else None,
            )

        return await loop.run_in_executor(None, _do_download)

    @staticmethod
    def create_audio_source(
        song: Song,
        volume: float,
        volume_float_min: float,
        volume_float_max: float,
    ) -> discord.AudioSource:
        """Creates an audio source using core.ffmpeg with volume control."""
        logger.debug("Creating audio source for song '%s' (volume=%.2f)", song.title, volume)
        return core_create_audio_source(
            source=song.stream_url,
            is_stream=True,
            volume=volume,
            volume_min=volume_float_min,
            volume_max=volume_float_max,
        )
