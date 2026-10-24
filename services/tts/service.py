from __future__ import annotations
import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional

import discord
from discord import app_commands
from discord.ext import commands

from core.service_base import BaseService
from services.tts.tts_engine import TTSEngine
from core.voice_queue import AudioTrack, GuildAudioPlayer

if TYPE_CHECKING:
    from core.bot import ModularBot

logger = logging.getLogger("bot.service.tts")

POPULAR_VOICES = [
    ("Jenny (en-US - Female)", "en-US-JennyNeural"),
    ("Guy (en-US - Male)", "en-US-GuyNeural"),
    ("Aria (en-US - Female)", "en-US-AriaNeural"),
    ("Francisca (pt-BR - Female)", "pt-BR-FranciscaNeural"),
    ("Antonio (pt-BR - Male)", "pt-BR-AntonioNeural"),
    ("Thalita (pt-BR - Multilingual)", "pt-BR-ThalitaMultilingualNeural"),
    ("Raquel (pt-PT - Female)", "pt-PT-RaquelNeural"),
    ("Duarte (pt-PT - Male)", "pt-PT-DuarteNeural"),
]

SPEED_CHOICES = [
    ("0.5x (Slowest)", "0.5x"),
    ("0.6x", "0.6x"),
    ("0.7x", "0.7x"),
    ("0.8x (Slower)", "0.8x"),
    ("0.9x", "0.9x"),
    ("1.0x (Normal / Default)", "1.0x"),
    ("1.1x", "1.1x"),
    ("1.2x (Faster)", "1.2x"),
    ("1.3x", "1.3x"),
    ("1.4x", "1.4x"),
    ("1.5x (Fast)", "1.5x"),
    ("1.6x", "1.6x"),
    ("1.7x", "1.7x"),
    ("1.8x", "1.8x"),
    ("1.9x", "1.9x"),
    ("2.0x (Very Fast)", "2.0x"),
]

DELAY_CHOICES = [
    ("0.0s (Simultaneous)", "0.0s"),
    ("0.2s", "0.2s"),
    ("0.3s", "0.3s"),
    ("0.4s", "0.4s"),
    ("0.5s", "0.5s"),
    ("0.6s", "0.6s"),
    ("0.7s", "0.7s"),
    ("0.8s", "0.8s"),
    ("1.0s (Default)", "1.0s"),
    ("1.2s", "1.2s"),
    ("1.5s", "1.5s"),
    ("2.0s", "2.0s"),
]

TIMEOUT_CHOICES = [
    ("0 (Never disconnect)", 0),
    ("60s (1 minute)", 60),
    ("120s (2 minutes)", 120),
    ("180s (3 minutes - Default)", 180),
    ("300s (5 minutes)", 300),
    ("600s (10 minutes)", 600),
    ("1800s (30 minutes)", 1800),
]


class TTSService(BaseService):
    """Modular Text-to-Speech (TTS) service using Edge-TTS neural voices and sound cues."""

    name: str = "tts"

    def __init__(self, bot: ModularBot, config: Optional[dict] = None) -> None:
        super().__init__(bot, config)
        self.engine = TTSEngine()
        self._connect_locks: Dict[int, asyncio.Lock] = {}

    def _get_connect_lock(self, guild_id: int) -> asyncio.Lock:
        """Retrieves or creates an asyncio.Lock per guild to serialize voice connections."""
        if guild_id not in self._connect_locks:
            self._connect_locks[guild_id] = asyncio.Lock()
        return self._connect_locks[guild_id]

    async def _ensure_voice_connection(
        self, guild: discord.Guild, target_channel: discord.VoiceChannel
    ) -> Optional[discord.VoiceClient]:
        """Ensures safe, serialized connection to the target voice channel without race conditions."""
        async with self._get_connect_lock(guild.id):
            vc = guild.voice_client

            if vc:
                if vc.is_connected():
                    if vc.channel and vc.channel.id != target_channel.id:
                        try:
                            await vc.move_to(target_channel)
                        except Exception as e:
                            logger.error(
                                "Failed to move to voice channel %s in guild %s: %s",
                                target_channel.id,
                                guild.id,
                                e,
                            )
                    return vc
                else:
                    # Stale or disconnected client; clean up safely without interrupting active gateway
                    try:
                        await vc.disconnect(force=True)
                    except Exception:
                        pass
                    await asyncio.sleep(0.2)

            try:
                return await target_channel.connect(reconnect=True, timeout=15.0)
            except discord.ClientException:
                vc = guild.voice_client
                if vc and vc.is_connected() and vc.channel and vc.channel.id != target_channel.id:
                    try:
                        await vc.move_to(target_channel)
                    except Exception:
                        pass
                return vc
            except Exception as e:
                logger.error(
                    "Failed to connect to voice channel %s in guild %s: %s",
                    target_channel.id,
                    guild.id,
                    e,
                )
                return None

    def get_player(self, guild: discord.Guild) -> GuildAudioPlayer:
        """Retrieves the unified audio player for this guild from the bot core."""
        return self.bot.get_audio_player(guild.id)

    def get_service_volume(self, guild_id: Optional[int]) -> float:
        """Returns the configured TTS playback volume as float (0.0 - 2.0)."""
        raw_vol = self.get_guild_setting(
            guild_id, "default_volume", self.config.get("default_volume", 90)
        )
        try:
            vol = float(raw_vol)
            if vol > 2.0:
                vol = vol / 100.0
            return max(0.0, min(vol, 2.0))
        except (ValueError, TypeError):
            return 0.9

    async def on_service_unload(self) -> None:
        """Cleans up service upon unloading."""
        pass

    def get_guild_speed(self, guild_id: Optional[int]) -> float:
        """Returns the configured speed multiplier for a guild (default 1.0)."""
        default_speed = self.config.get("default_speed", 1.0)
        val = self.get_guild_setting(guild_id, "default_speed", default_speed)
        try:
            return round(float(val), 1)
        except (ValueError, TypeError):
            return 1.0

    def get_guild_intro_delay(self, guild_id: Optional[int]) -> float:
        """Returns the configured delay in seconds before speech starts over the intro sound."""
        default_delay = self.config.get("intro_delay", 1.0)
        val = self.get_guild_setting(guild_id, "intro_delay", default_delay)
        try:
            return round(float(val), 2)
        except (ValueError, TypeError):
            return round(float(default_delay), 2)

    def get_guild_timeout(self, guild_id: Optional[int]) -> int:
        """Returns configured inactivity timeout in seconds from the bot (0 = never disconnect)."""
        if hasattr(self.bot, "get_guild_timeout"):
            return self.bot.get_guild_timeout(guild_id)
        return int(self.config.get("auto_disconnect_timeout", 300))

    def _speed_to_rate(self, speed: float) -> str:
        """Converts speed multiplier (e.g. 1.0, 1.2, 0.8) to Edge-TTS rate string (+0%, +20%, -20%)."""
        percentage = round((speed - 1.0) * 100)
        sign = "+" if percentage >= 0 else ""
        return f"{sign}{percentage}%"

    def get_available_sounds(self) -> List[str]:
        """Scans the audio sounds directory and returns a sorted list of audio filenames."""
        sounds_dir_str = self.config.get("sounds_dir", "assets/sounds")
        sounds_dir = Path(sounds_dir_str)
        if not sounds_dir.exists():
            return []
        files = [
            f.name
            for f in sounds_dir.iterdir()
            if f.is_file() and f.suffix.lower() in (".mp3", ".wav", ".ogg", ".opus")
        ]
        return sorted(files)

    async def _connect_voice(
        self, interaction: discord.Interaction
    ) -> Optional[discord.VoiceClient]:
        """Ensures the bot is connected to the user's voice channel."""
        if not interaction.guild:
            msg = "This command can only be used within a server."
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
            return None

        user = interaction.user
        if not isinstance(user, discord.Member) or not user.voice or not user.voice.channel:
            msg = "You must be connected to a voice channel to use TTS."
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
            return None

        target_channel = user.voice.channel
        vc = await self._ensure_voice_connection(interaction.guild, target_channel)
        if not vc:
            msg = f"Unable to connect to voice channel `{target_channel.name}`."
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
            return None
        return vc

    # Autocomplete handler for popular voice names
    async def _voice_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> List[app_commands.Choice[str]]:
        choices = []
        for label, val in POPULAR_VOICES:
            if current.lower() in label.lower() or current.lower() in val.lower():
                choices.append(app_commands.Choice(name=label, value=val))
        return choices[:25]

    # Autocomplete handler for speed multipliers
    async def _speed_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> List[app_commands.Choice[str]]:
        choices = []
        for label, val in SPEED_CHOICES:
            if current.lower() in label.lower() or current.lower() in val.lower():
                choices.append(app_commands.Choice(name=label, value=val))
        return choices[:25]

    # Autocomplete handler for delay options
    async def _delay_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> List[app_commands.Choice[str]]:
        choices = []
        for label, val in DELAY_CHOICES:
            if current.lower() in label.lower() or current.lower() in val.lower():
                choices.append(app_commands.Choice(name=label, value=val))
        return choices[:25]

    # Autocomplete handler for inactivity timeout
    async def _timeout_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> List[app_commands.Choice[int]]:
        choices = []
        for label, val in TIMEOUT_CHOICES:
            if current.lower() in label.lower() or current in str(val):
                choices.append(app_commands.Choice(name=label, value=val))
        return choices[:25]

    # Autocomplete handler for audio sound effects in assets/sounds/
    async def _sound_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> List[app_commands.Choice[str]]:
        choices = [app_commands.Choice(name="None (Disabled)", value="none")]
        sounds = self.get_available_sounds()
        for s in sounds:
            if current.lower() in s.lower():
                clean_name = s.rsplit(".", 1)[0].replace("_", " ").title()
                choices.append(app_commands.Choice(name=f"{clean_name} ({s})", value=s))
        return choices[:25]

    # --- SLASH COMMAND GROUP (/tts) ---
    tts_group = app_commands.Group(name="tts", description="Text-to-Speech service commands")

    async def _exec_speak(self, interaction: discord.Interaction, text: str):
        """Unified execution logic for speech synthesis and voice playback."""
        guild = interaction.guild
        if not guild:
            await interaction.response.send_message(
                "This command can only be used inside a server.", ephemeral=True
            )
        # Defer response first to allow voice connection and asynchronous audio synthesis
        await interaction.response.defer()

        vc = await self._connect_voice(interaction)
        if not vc:
            return

        # Guild-specific or fallback default settings
        max_len = int(self.get_guild_setting(guild.id, "max_text_length", 350))
        filter_urls = bool(self.get_guild_setting(guild.id, "filter_urls", True))
        voice = str(self.get_guild_setting(guild.id, "default_voice", "pt-BR-FranciscaNeural"))

        # Calculate rate string from 0.1x speed multiplier
        speed = self.get_guild_speed(guild.id)
        rate = self._speed_to_rate(speed)

        cleaned_text = self.engine.clean_text(text, max_length=max_len, filter_urls=filter_urls)
        if not cleaned_text:
            await interaction.followup.send("The provided text is invalid or empty.")
            return

        try:
            audio_path = await self.engine.synthesize(
                text=cleaned_text,
                voice=voice,
                rate=rate,
            )
        except Exception as e:
            logger.error("Audio synthesis failed for guild %s: %s", guild.id, e)
            await interaction.followup.send(f"Error generating TTS audio: {e}")
            return

        # Mix intro sound with speech if enabled
        intro_sound = str(self.get_guild_setting(guild.id, "intro_sound", "none")).strip()
        if intro_sound and intro_sound.lower() != "none":
            sounds_dir_str = self.config.get("sounds_dir", "assets/sounds")
            intro_path = Path(sounds_dir_str) / intro_sound
            if intro_path.exists():
                intro_delay = self.get_guild_intro_delay(guild.id)
                ffmpeg_path = self.get_guild_setting(guild.id, "ffmpeg_path", "ffmpeg")
                audio_path = await self.engine.mix_with_intro(
                    speech_path=audio_path,
                    intro_path=intro_path,
                    delay_seconds=intro_delay,
                    ffmpeg_path=ffmpeg_path,
                )

        player = self.get_player(guild)
        track = AudioTrack(
            title=f"TTS: {cleaned_text[:40]}" if len(cleaned_text) > 40 else f"TTS: {cleaned_text}",
            source=audio_path,
            volume=self.get_service_volume(guild.id),
            service_name="tts",
            requester=interaction.user.display_name,
            channel=interaction.channel,
            text=cleaned_text,
            is_temporary=True,
            options="-loglevel error",
        )

        pos = await player.add_track(track)
        if pos == 0:
            await interaction.followup.send(f"**{interaction.user.display_name}**: \"{cleaned_text}\"")
        else:
            await interaction.followup.send(
                f"Added to speech queue (#{pos}): \"{cleaned_text}\""
            )

    # --- /tts COMMAND GROUP ---
    @tts_group.command(name="speak", description="Speaks text in current voice channel.")
    async def cmd_tts_speak(self, interaction: discord.Interaction, text: str):
        await self._exec_speak(interaction, text)

    @tts_group.command(name="voices", description="Lists popular available neural voices.")
    async def cmd_tts_voices(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="Available Neural Voices (Edge-TTS)",
            description="Use `/tts set_voice <name>` to set your server's voice:",
            color=discord.Color.green(),
        )

        en_voices = []
        pt_br = []
        pt_pt = []

        for label, val in POPULAR_VOICES:
            line = f"• **{val}** ({label.split(' - ')[0]})"
            if "en-" in val:
                en_voices.append(line)
            elif "pt-BR" in val:
                pt_br.append(line)
            elif "pt-PT" in val:
                pt_pt.append(line)

        embed.add_field(name="English (US)", value="\n".join(en_voices) or "None", inline=False)
        embed.add_field(name="Portuguese (Brazil)", value="\n".join(pt_br) or "None", inline=False)
        embed.add_field(name="Portuguese (Portugal)", value="\n".join(pt_pt) or "None", inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @tts_group.command(name="config", description="Shows current TTS configuration for this server.")
    async def cmd_tts_config(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            await interaction.response.send_message("Command only available in servers.", ephemeral=True)
            return

        cfg = self.get_effective_config(guild.id)
        voice = cfg.get("default_voice", "pt-BR-FranciscaNeural")
        speed = self.get_guild_speed(guild.id)
        intro_sound = self.get_guild_setting(guild.id, "intro_sound", "none")
        intro_display = f"`{intro_sound}`" if intro_sound and intro_sound != "none" else "None (disabled)"
        intro_delay = self.get_guild_intro_delay(guild.id)
        bound_ch_id = self.get_guild_setting(guild.id, "bound_channel_id")
        bound_ch_str = f"<#{bound_ch_id}>" if bound_ch_id else "None (uses `/tts speak` commands)"
        timeout = self.get_guild_timeout(guild.id)
        timeout_str = "Never (disabled)" if timeout == 0 else f"{timeout}s ({timeout // 60}m)" if timeout >= 60 else f"{timeout}s"

        embed = discord.Embed(
            title=f"TTS Configuration - {guild.name}",
            color=discord.Color.blue(),
        )
        embed.add_field(name="Current Voice", value=f"`{voice}`", inline=True)
        embed.add_field(name="Speech Speed", value=f"`{speed:.1f}x`", inline=True)
        embed.add_field(name="Intro Sound", value=intro_display, inline=True)
        embed.add_field(name="Intro Delay", value=f"`{intro_delay:.1f}s`", inline=True)
        embed.add_field(name="Speech Volume", value=f"`{int(self.get_service_volume(guild.id) * 100)}%`", inline=True)
        embed.add_field(name="Auto-Disconnect Timeout", value=timeout_str, inline=True)
        embed.add_field(name="Auto-Reading Channel", value=bound_ch_str, inline=False)
        embed.add_field(
            name="Configuration Commands",
            value=(
                "• `/tts set_voice`: change server default voice\n"
                "• `/tts set_speed`: adjust speech speed (e.g., `1.0x`, `1.2x`, `0.8x`)\n"
                "• `/tts set_volume`: adjust speech volume (1-100%)\n"
                "• `/tts set_intro`: choose sound cue played before message\n"
                "• `/tts set_intro_delay`: delay before speech starts over intro (e.g. `1.0s`)\n"
                "• `/bot set_auto_disconnect_timeout`: set voice inactivity timeout (0 = never disconnect)\n"
                "• `/tts set_channel`: set a text channel for automatic speech"
            ),
            inline=False,
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @tts_group.command(name="set_voice", description="Sets the default neural TTS voice for this server.")
    @app_commands.describe(voice="Select the desired neural voice")
    @app_commands.autocomplete(voice=_voice_autocomplete)
    @app_commands.default_permissions(manage_guild=True)
    async def cmd_tts_set_voice(self, interaction: discord.Interaction, voice: str):
        if not interaction.guild:
            await interaction.response.send_message("Command only available in servers.", ephemeral=True)
            return

        await self.set_guild_setting(interaction.guild.id, "default_voice", voice)
        await interaction.response.send_message(
            f"Server voice successfully updated to: `{voice}`"
        )

    @tts_group.command(
        name="set_speed",
        description="Sets the speech playback speed (starts at 1.0x, in 0.1x steps, e.g., 1.1x, 0.9x).",
    )
    @app_commands.describe(speed="Speed multiplier (e.g., 1.0x, 1.1x, 1.2x, 0.8x)")
    @app_commands.autocomplete(speed=_speed_autocomplete)
    @app_commands.default_permissions(manage_guild=True)
    async def cmd_tts_set_speed(self, interaction: discord.Interaction, speed: str):
        if not interaction.guild:
            await interaction.response.send_message("Command only available in servers.", ephemeral=True)
            return

        cleaned = speed.lower().rstrip("x").strip()
        try:
            speed_val = round(float(cleaned), 1)
        except ValueError:
            await interaction.response.send_message(
                "Invalid speed format! Please provide a multiplier like `1.0x`, `1.1x`, or `0.8x`.",
                ephemeral=True,
            )
            return

        if speed_val < 0.5 or speed_val > 3.0:
            await interaction.response.send_message(
                "Speed multiplier must be between `0.5x` and `3.0x` (with 0.1x steps).",
                ephemeral=True,
            )
            return

        await self.set_guild_setting(interaction.guild.id, "default_speed", speed_val)
        await interaction.response.send_message(
            f"Speech speed successfully updated to: `{speed_val:.1f}x`"
        )

    @tts_group.command(
        name="set_intro",
        description="Sets a sound effect to play before each TTS message.",
    )
    @app_commands.describe(sound="Select an audio sound effect from assets/sounds/ (or None)")
    @app_commands.autocomplete(sound=_sound_autocomplete)
    @app_commands.default_permissions(manage_guild=True)
    async def cmd_tts_set_intro(self, interaction: discord.Interaction, sound: str):
        if not interaction.guild:
            await interaction.response.send_message("Command only available in servers.", ephemeral=True)
            return

        sound_clean = sound.strip()
        if sound_clean.lower() in ("none", "disabled", "off"):
            await self.set_guild_setting(interaction.guild.id, "intro_sound", "none")
            await interaction.response.send_message("ℹIntro sound effect disabled.")
            return

        available = self.get_available_sounds()
        if sound_clean not in available:
            await interaction.response.send_message(
                f"Sound file `{sound_clean}` was not found in `assets/sounds/`. Use the autocomplete options.",
                ephemeral=True,
            )
            return

        await self.set_guild_setting(interaction.guild.id, "intro_sound", sound_clean)
        clean_title = sound_clean.rsplit(".", 1)[0].replace("_", " ").title()
        delay_val = self.get_guild_intro_delay(interaction.guild.id)
        await interaction.response.send_message(
            f"Intro sound effect successfully set to: **{clean_title}** (`{sound_clean}`)!\n"
            f"Speech will begin {delay_val:.1f}s after the intro sound starts."
        )

    @tts_group.command(
        name="set_intro_delay",
        description="Sets the delay before speech starts playing over the intro sound.",
    )
    @app_commands.describe(delay="Delay in seconds before speech starts (e.g., 0.5s, 0.3s, 1.0s)")
    @app_commands.autocomplete(delay=_delay_autocomplete)
    @app_commands.default_permissions(manage_guild=True)
    async def cmd_tts_set_intro_delay(self, interaction: discord.Interaction, delay: str):
        if not interaction.guild:
            await interaction.response.send_message("Command only available in servers.", ephemeral=True)
            return

        cleaned = delay.lower().rstrip("s").strip()
        try:
            delay_val = round(float(cleaned), 2)
        except ValueError:
            await interaction.response.send_message(
                "Invalid format! Please enter a delay like `0.5s`, `0.3s`, or `1.0s`.",
                ephemeral=True,
            )
            return

        if delay_val < 0.0 or delay_val > 5.0:
            await interaction.response.send_message(
                "Delay must be between `0.0s` and `5.0s`.",
                ephemeral=True,
            )
            return

        await self.set_guild_setting(interaction.guild.id, "intro_delay", delay_val)
        await interaction.response.send_message(
            f"Intro sound delay set to: `{delay_val:.1f}s`!\n"
            f"Speech will now begin {delay_val:.1f}s after the intro sound starts."
        )



    @tts_group.command(
        name="set_channel",
        description="Configures a text channel to be automatically read aloud in voice chat.",
    )
    @app_commands.describe(
        channel="Text channel to monitor (leave empty to disable auto-reading)"
    )
    @app_commands.default_permissions(manage_guild=True)
    async def cmd_tts_set_channel(
        self, interaction: discord.Interaction, channel: Optional[discord.TextChannel] = None
    ):
        if not interaction.guild:
            await interaction.response.send_message("Command only available in servers.", ephemeral=True)
            return

        if channel is None:
            await self.set_guild_setting(interaction.guild.id, "bound_channel_id", None)
            await interaction.response.send_message(
                "Auto-reading disabled. Use `/tts speak` to synthesize speech on demand."
            )
        else:
            await self.set_guild_setting(interaction.guild.id, "bound_channel_id", channel.id)
            await interaction.response.send_message(
                f"Auto-reading channel set to {channel.mention}!\n"
                f"When you send messages in this channel, the bot will automatically join your voice channel and read them aloud."
            )

    @tts_group.command(name="set_volume", description="Sets the default TTS speech volume for this server (1-100%).")
    @app_commands.describe(level="Volume level from 1 to 100")
    @app_commands.default_permissions(manage_guild=True)
    async def cmd_tts_set_volume(self, interaction: discord.Interaction, level: int):
        guild = interaction.guild
        if not guild:
            await interaction.response.send_message("Command only available in servers.", ephemeral=True)
            return

        if level < 1 or level > 100:
            await interaction.response.send_message("Volume must be between 1 and 100.", ephemeral=True)
            return

        vol_float = level / 100.0
        await self.set_guild_setting(guild.id, "default_volume", level)

        player = self.get_player(guild)
        if player.current_track and player.current_track.service_name == "tts":
            player.set_current_volume(vol_float)

        await interaction.response.send_message(f"TTS speech volume set to **{level}%**.")

    # --- AUTO-READING (CHAT TO SPEECH) ---
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """Reads messages sent in configured bound channel when bot is connected to voice."""
        if not message.guild or message.author.bot:
            return

        prefix = self.bot.bot_config.get("prefix", "!")
        if message.content.startswith(prefix):
            return

        bound_channel_id = self.get_guild_setting(message.guild.id, "bound_channel_id")
        if not bound_channel_id or message.channel.id != bound_channel_id:
            return

        # Do not read if the message contains files, attachments, or stickers
        if message.attachments or message.stickers:
            return

        # Ensure bot is in the voice channel of the message author
        author = message.author
        if not isinstance(author, discord.Member):
            return

        author_channel = author.voice.channel if author.voice else None
        vc = message.guild.voice_client

        if author_channel:
            vc = await self._ensure_voice_connection(message.guild, author_channel)
            if not vc:
                return
        else:
            # Author is not in a voice channel; only proceed if bot is already connected
            if not vc or not vc.is_connected():
                return

        max_len = int(self.get_guild_setting(message.guild.id, "max_text_length", 350))
        filter_urls = bool(self.get_guild_setting(message.guild.id, "filter_urls", True))
        voice = str(self.get_guild_setting(message.guild.id, "default_voice", "pt-BR-FranciscaNeural"))

        # Calculate rate string from 0.1x speed multiplier
        speed = self.get_guild_speed(message.guild.id)
        rate = self._speed_to_rate(speed)

        text_to_speak = message.clean_content
        cleaned = self.engine.clean_text(text_to_speak, max_length=max_len, filter_urls=filter_urls)
        if not cleaned:
            return

        try:
            audio_path = await self.engine.synthesize(
                text=cleaned,
                voice=voice,
                rate=rate,
            )

            # Mix intro sound with speech if enabled
            intro_sound = str(self.get_guild_setting(message.guild.id, "intro_sound", "none")).strip()
            if intro_sound and intro_sound.lower() != "none":
                sounds_dir_str = self.config.get("sounds_dir", "assets/sounds")
                intro_path = Path(sounds_dir_str) / intro_sound
                if intro_path.exists():
                    intro_delay = self.get_guild_intro_delay(message.guild.id)
                    ffmpeg_path = self.get_guild_setting(message.guild.id, "ffmpeg_path", "ffmpeg")
                    audio_path = await self.engine.mix_with_intro(
                        speech_path=audio_path,
                        intro_path=intro_path,
                        delay_seconds=intro_delay,
                        ffmpeg_path=ffmpeg_path,
                    )

            player = self.get_player(message.guild)
            track = AudioTrack(
                title=f"TTS: {cleaned[:40]}" if len(cleaned) > 40 else f"TTS: {cleaned}",
                source=audio_path,
                volume=self.get_service_volume(message.guild.id),
                service_name="tts",
                requester=message.author.display_name,
                channel=message.channel,
                text=cleaned,
                is_temporary=True,
                options="-loglevel error",
            )
            await player.add_track(track)
        except Exception as e:
            logger.error("Failed to synthesize automatic chat message in guild %s: %s", message.guild.id, e)
