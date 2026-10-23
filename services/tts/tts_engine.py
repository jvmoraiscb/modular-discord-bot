import asyncio
import logging
import re
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import edge_tts

logger = logging.getLogger("bot.service.tts.engine")


class TTSEngine:
    """Text-to-Speech synthesis engine using Microsoft Edge-TTS neural voices."""

    def __init__(self, temp_dir: str = "data/temp") -> None:
        self.temp_dir = Path(temp_dir)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self._voices_cache: Optional[List[Dict[str, Any]]] = None

    def clean_text(
        self,
        text: str,
        max_length: int = 350,
        filter_urls: bool = True,
    ) -> str:
        """Cleans and sanitizes raw input text for natural speech synthesis."""
        if not text:
            return ""

        # Replace channel mentions <#123> and user mentions <@123>
        text = re.sub(r"<@!?(\d+)>", "user", text)
        text = re.sub(r"<@&(\d+)>", "role", text)
        text = re.sub(r"<#(\d+)>", "channel", text)

        # Replace Discord custom emojis <:name:123> with 'name'
        text = re.sub(r"<a?:(\w+):\d+>", r"\1", text)

        # Replace or filter URLs to avoid reading long link strings
        if filter_urls:
            text = re.sub(r"https?://\S+", "link", text)

        # Collapse excessive whitespace
        text = re.sub(r"\s+", " ", text).strip()

        # Enforce maximum text length
        if len(text) > max_length:
            text = text[:max_length].rstrip() + "..."

        return text

    async def synthesize(
        self,
        text: str,
        voice: str = "pt-BR-FranciscaNeural",
        rate: str = "+0%",
        pitch: str = "+0Hz",
        volume: str = "+0%",
    ) -> Path:
        """Synthesizes text into an MP3 audio file and returns its path."""
        if not text.strip():
            raise ValueError("Input text for synthesis cannot be empty.")

        output_filename = f"tts_{uuid.uuid4().hex}.mp3"
        output_path = self.temp_dir / output_filename

        communicate = edge_tts.Communicate(
            text=text,
            voice=voice,
            rate=rate,
            pitch=pitch,
            volume=volume,
        )

        try:
            await communicate.save(str(output_path))
            return output_path
        except Exception as e:
            logger.error("Error during speech synthesis (voice: %s): %s", voice, e)
            if output_path.exists():
                output_path.unlink(missing_ok=True)
            raise

    async def mix_with_intro(
        self,
        speech_path: Path,
        intro_path: Path,
        delay_seconds: float = 0.5,
        ffmpeg_path: str = "ffmpeg",
    ) -> Path:
        """Mixes intro sound with speech so speech starts playing after delay_seconds."""
        if not intro_path.exists():
            return speech_path

        delay_ms = max(0, int(delay_seconds * 1000))
        mixed_filename = f"tts_mixed_{uuid.uuid4().hex}.mp3"
        mixed_path = self.temp_dir / mixed_filename

        filter_complex = (
            f"[1:a]adelay={delay_ms}|{delay_ms}[delayed];"
            f"[0:a][delayed]amix=inputs=2:duration=longest:normalize=0"
        )
        cmd = [
            ffmpeg_path,
            "-y",
            "-i", str(intro_path),
            "-i", str(speech_path),
            "-filter_complex", filter_complex,
            "-loglevel", "error",
            str(mixed_path),
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

            # Remove original unmixed speech file
            speech_path.unlink(missing_ok=True)
            return mixed_path
        except Exception as e:
            logger.error("Exception during audio mixing: %s", e)
            return speech_path

    async def get_available_voices(self, filter_prefix: Optional[str] = "pt-") -> List[Dict[str, str]]:
        """Returns a list of available Edge-TTS voices filtered by locale prefix (e.g., 'pt-')."""
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
            if not filter_prefix or short_name.lower().startswith(filter_prefix.lower()):
                results.append({
                    "name": short_name,
                    "gender": v.get("Gender", "Unknown"),
                    "locale": v.get("Locale", "Unknown"),
                    "friendly_name": v.get("FriendlyName", short_name),
                })
        return results

