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

    _FFMPEG_EXECUTABLE = executable
    _STREAM_BEFORE_OPTIONS = stream_before_options
    _STREAM_OPTIONS = stream_options
    _LOCAL_FILE_OPTIONS = local_file_options


def set_ffmpeg_path(path: str) -> None:
    """Sets the global FFmpeg executable path configured by the bot core."""
    global _FFMPEG_EXECUTABLE
    _FFMPEG_EXECUTABLE = path


def get_ffmpeg_path() -> str:
    """Returns the current FFmpeg executable path."""
    return _FFMPEG_EXECUTABLE


def verify_ffmpeg(executable: Optional[str] = None) -> bool:
    """Verifies that the FFmpeg executable is accessible and runnable."""
    bin_path = executable or _FFMPEG_EXECUTABLE
    if shutil.which(bin_path):
        return True
    try:
        res = subprocess.run(
            [bin_path, "-version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return res.returncode == 0
    except Exception:
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
        return speech_path

    sr = int(sample_rate)
    intro_vol = float(intro_volume)
    speech_vol = float(speech_volume)
    lim = float(limiter_limit)
    delay_ms = max(0, int(delay_seconds * 1000))

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
        return output_path
    except Exception as e:
        logger.error("Exception during FFmpeg audio mixing: %s", e)
        return speech_path
