"""Centralized FFmpeg audio processing and streaming management for the bot core."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
import shutil
import subprocess
from typing import Optional, Union

import discord

logger = logging.getLogger("bot.core.ffmpeg")

_FFMPEG_EXECUTABLE: str = ""
_STREAM_BEFORE_OPTIONS: str = ""
_STREAM_OPTIONS: str = ""
_LOCAL_FILE_OPTIONS: str = ""


def configure_ffmpeg(
    *,
    executable: str,
    stream_before_options: str,
    stream_options: str,
    local_file_options: str,
) -> None:
    """Initializes FFmpeg runtime parameters from the root BotConfig."""
    global _FFMPEG_EXECUTABLE, _STREAM_BEFORE_OPTIONS, _STREAM_OPTIONS, _LOCAL_FILE_OPTIONS

    _FFMPEG_EXECUTABLE = shutil.which(executable) or executable
    _STREAM_BEFORE_OPTIONS = stream_before_options
    _STREAM_OPTIONS = stream_options
    _LOCAL_FILE_OPTIONS = local_file_options
    logger.info("Configured FFmpeg executable: %s", _FFMPEG_EXECUTABLE)


def set_ffmpeg_path(path: str) -> None:
    """Sets the global FFmpeg executable path configured by the bot core."""
    global _FFMPEG_EXECUTABLE
    _FFMPEG_EXECUTABLE = shutil.which(path) or path
    logger.info("Updated FFmpeg executable path: %s", _FFMPEG_EXECUTABLE)


def get_ffmpeg_path() -> str:
    """Returns the current FFmpeg executable path (resolved to absolute path if available on PATH)."""
    return shutil.which(_FFMPEG_EXECUTABLE) or _FFMPEG_EXECUTABLE


def verify_ffmpeg(executable: Optional[str] = None) -> bool:
    """Verifies that the FFmpeg executable is accessible and runnable."""
    bin_path = executable or _FFMPEG_EXECUTABLE
    if shutil.which(bin_path):
        logger.debug("Verified FFmpeg binary on PATH: %s", bin_path)
        return True
    try:
        res = subprocess.run(
            [bin_path, "-version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        ok = res.returncode == 0
        if not ok:
            logger.warning("FFmpeg verification failed with return code %d for '%s'", res.returncode, bin_path)
        return ok
    except Exception as e:
        logger.warning("FFmpeg verification raised exception for '%s': %s", bin_path, e)
        return False


def create_audio_source(
    source: Union[str, Path],
    *,
    is_stream: bool,
    volume: float,
    volume_min: float,
    volume_max: float,
    before_options: Optional[str] = None,
    options: Optional[str] = None,
) -> discord.AudioSource:
    """Creates a discord.py audio source using the core FFmpeg configuration and required volume bounds."""
    source_str = str(source)

    if before_options is None:
        before_options = _STREAM_BEFORE_OPTIONS if is_stream else ""

    if options is None:
        options = _STREAM_OPTIONS if is_stream else _LOCAL_FILE_OPTIONS

    pcm_audio = discord.FFmpegPCMAudio(
        source_str,
        executable=_FFMPEG_EXECUTABLE,
        before_options=before_options,
        options=options,
    )

    clamped_vol = max(float(volume_min), min(float(volume), float(volume_max)))
    logger.debug(
        "Created FFmpeg audio source (is_stream=%s, volume=%.2f)",
        is_stream,
        clamped_vol,
    )
    return discord.PCMVolumeTransformer(pcm_audio, volume=clamped_vol)


async def mix_audio_with_intro(
    speech_path: Path,
    intro_path: Path,
    output_path: Path,
    *,
    delay_seconds: float,
    sample_rate: int,
    intro_volume: float,
    speech_volume: float,
    limiter_limit: float,
) -> Path:
    """Mixes an intro sound effect with speech audio using the core FFmpeg executable."""
    if not intro_path.exists():
        logger.warning("Intro sound file '%s' not found; skipping intro mix.", intro_path)
        return speech_path

    sr = int(sample_rate)
    intro_vol = float(intro_volume)
    speech_vol = float(speech_volume)
    lim = float(limiter_limit)
    delay_ms = max(0, int(delay_seconds * 1000))

    logger.info(
        "Mixing speech '%s' with intro '%s' (delay=%dms)",
        speech_path.name,
        intro_path.name,
        delay_ms,
    )

    filter_complex = (
        f"[0:a]aresample={sr},aformat=sample_fmts=s16:channel_layouts=stereo,volume={intro_vol}[a0];"
        f"[1:a]aresample={sr},aformat=sample_fmts=s16:channel_layouts=stereo,volume={speech_vol},adelay={delay_ms}|{delay_ms}[a1];"
        f"[a0][a1]amix=inputs=2:duration=longest:normalize=0,alimiter=limit={lim}[out]"
    )

    cmd = [
        _FFMPEG_EXECUTABLE,
        "-y",
        "-i", str(intro_path),
        "-i", str(speech_path),
        "-filter_complex", filter_complex,
        "-map", "[out]",
        "-ar", str(sr),
        "-ac", "2",
        "-loglevel", "error",
        str(output_path),
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()

        if proc.returncode != 0:
            logger.error("FFmpeg mixing failed: %s", stderr.decode("utf-8", errors="replace"))
            return speech_path

        speech_path.unlink(missing_ok=True)
        logger.info("Successfully mixed intro audio into '%s'", output_path.name)
        return output_path
    except Exception as e:
        logger.error("Exception during FFmpeg audio mixing: %s", e)
        return speech_path


def trim_media_file(
    input_path: Path,
    output_path: Path,
    *,
    start_seconds: int,
    end_seconds: int,
) -> Path:
    """Synchronously trims a media file between start_seconds and end_seconds using the core FFmpeg executable."""
    logger.info(
        "Trimming media '%s' -> '%s' (start=%ds, end=%ds)",
        input_path.name,
        output_path.name,
        start_seconds,
        end_seconds,
    )
    cmd = [
        _FFMPEG_EXECUTABLE,
        "-y",
        "-ss", str(start_seconds),
        "-to", str(end_seconds),
        "-i", str(input_path),
        "-c", "copy",
        "-loglevel", "error",
        str(output_path),
    ]
    res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if res.returncode != 0 or not output_path.exists() or output_path.stat().st_size == 0:
        logger.warning(
            "Fast stream-copy trim failed or produced empty file for '%s'; falling back to re-encoding.",
            input_path.name,
        )
        fallback_cmd = [
            _FFMPEG_EXECUTABLE,
            "-y",
            "-ss", str(start_seconds),
            "-to", str(end_seconds),
            "-i", str(input_path),
            "-loglevel", "error",
            str(output_path),
        ]
        res_fb = subprocess.run(fallback_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        if res_fb.returncode != 0:
            err_msg = res_fb.stderr.decode("utf-8", errors="replace")
            logger.error("FFmpeg media trim failed: %s", err_msg)
            raise RuntimeError(f"Failed to trim media file: {err_msg}")

    input_path.unlink(missing_ok=True)
    logger.info(
        "Finished trimming media '%s' (%d bytes)",
        output_path.name,
        output_path.stat().st_size if output_path.exists() else 0,
    )
    return output_path

