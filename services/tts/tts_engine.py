"""Edge-TTS speech synthesis engine delegating audio mixing to core.ffmpeg."""
from __future__ import annotations

import logging
from pathlib import Path
import re
from typing import Any, Dict, List, Optional
import uuid

import edge_tts

from core.ffmpeg import mix_audio_with_intro
from services.tts.models import TTSConfig

logger = logging.getLogger("bot.service.tts.engine")


class TTSEngine:
    """Text-to-Speech synthesis engine using Microsoft Edge-TTS neural voices."""

    def __init__(self, config: TTSConfig) -> None:
        self.config = config
        self.temp_dir = Path(config.temp_dir)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self._voices_cache: Optional[List[Dict[str, Any]]] = None

    def clean_text(
        self,
        text: str,
        max_length: Optional[int] = None,
        filter_urls: Optional[bool] = None,
    ) -> str:
        """Cleans and sanitizes raw input text for natural speech synthesis."""
        if not text:
            return ""

        limit = int(self.config.max_text_length if max_length is None else max_length)
        should_filter_urls = bool(self.config.filter_urls if filter_urls is None else filter_urls)

        # Replace channel mentions <#123> and user mentions <@123>
        text = re.sub(r"<@!?(\d+)>", "user", text)
        text = re.sub(r"<@&(\d+)>", "role", text)
        text = re.sub(r"<#(\d+)>", "channel", text)

        # Replace Discord custom emojis <:name:123> with 'name'
        text = re.sub(r"<a?:(\w+):\d+>", r"\1", text)

        # Remove URLs completely to avoid reading links or saying 'link'
        if should_filter_urls:
            text = re.sub(r"<?(?:https?://\S+|www\.\S+)>?", "", text)

        # Collapse excessive whitespace
        text = re.sub(r"\s+", " ", text).strip()

        # If only isolated punctuation remains after URL removal, clear it
        if should_filter_urls and not any(c.isalnum() for c in text):
            return ""

        # Enforce maximum text length
        if len(text) > limit:
            text = text[:limit].rstrip() + "..."

        return text

    async def synthesize(
        self,
        text: str,
        voice: Optional[str] = None,
        rate: Optional[str] = None,
        pitch: Optional[str] = None,
        volume: Optional[str] = None,
    ) -> Path:
        """Synthesizes text into an MP3 audio file and returns its path."""
        if not text.strip():
            raise ValueError("Input text for synthesis cannot be empty.")

        selected_voice = voice or self.config.voice
        selected_rate = rate or self.config.rate
        selected_pitch = pitch or self.config.pitch
        selected_volume = volume or self.config.synth_volume

        output_filename = f"tts_{uuid.uuid4().hex}.mp3"
        output_path = self.temp_dir / output_filename

        communicate = edge_tts.Communicate(
            text=text,
            voice=selected_voice,
            rate=selected_rate,
            pitch=selected_pitch,
            volume=selected_volume,
        )

        try:
            await communicate.save(str(output_path))
            return output_path
        except Exception as e:
            logger.error("Error during speech synthesis (voice: %s): %s", selected_voice, e)
            if output_path.exists():
                output_path.unlink(missing_ok=True)
            raise

    async def mix_with_intro(
        self,
        speech_path: Path,
        intro_path: Path,
        delay_seconds: float,
    ) -> Path:
        """Mixes intro sound with speech using core.ffmpeg.mix_audio_with_intro."""
        mixed_filename = f"tts_mixed_{uuid.uuid4().hex}.mp3"
        mixed_path = self.temp_dir / mixed_filename

        return await mix_audio_with_intro(
            speech_path=speech_path,
            intro_path=intro_path,
            output_path=mixed_path,
            delay_seconds=delay_seconds,
            sample_rate=int(self.config.sample_rate),
            intro_volume=float(self.config.mix_intro_volume),
            speech_volume=float(self.config.mix_speech_volume),
            limiter_limit=float(self.config.mix_limiter_limit),
        )

    async def get_available_voices(self, filter_prefix: Optional[str] = None) -> List[Dict[str, str]]:
        """Returns a list of available Edge-TTS voices filtered by locale prefix."""
        prefix = self.config.default_locale_filter if filter_prefix is None else filter_prefix
        if self._voices_cache is None:
            try:
                raw_voices = await edge_tts.list_voices()
                self._voices_cache = raw_voices
            except Exception as e:
                logger.error("Failed to fetch available voices from Edge-TTS: %s", e)
                return []

        results = []
        for v in self._voices_cache:
            short_name = v.get("ShortName", "")
            if not prefix or short_name.lower().startswith(prefix.lower()):
                results.append({
                    "name": short_name,
                    "gender": v.get("Gender", "Unknown"),
                    "locale": v.get("Locale", "Unknown"),
                    "friendly_name": v.get("FriendlyName", short_name),
                })
        return results
