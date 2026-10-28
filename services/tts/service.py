"""Modular Text-to-Speech (TTS) service using Edge-TTS neural voices and sound cues."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, ClassVar, Dict, List, Optional, TYPE_CHECKING, Type, Union

import discord
from discord import app_commands
from discord.ext import commands

from core.service_base import BaseService
from core.voice_queue import AudioTrack, GuildAudioPlayer
from services.tts.models import TTSConfig, TTSGuildConfig
from services.tts.tts_engine import TTSEngine

if TYPE_CHECKING:
    from core.bot import ModularBot

logger = logging.getLogger("bot.service.tts")


class TTSService(BaseService[TTSConfig, TTSGuildConfig]):
    """Modular Text-to-Speech (TTS) service using Edge-TTS neural voices and sound cues."""

    name: str = "tts"
    config_class: ClassVar[Type[TTSConfig]] = TTSConfig
    guild_config_class: ClassVar[Type[TTSGuildConfig]] = TTSGuildConfig

    def __init__(
        self,
        bot: ModularBot,
        config: Optional[Union[TTSConfig, Dict[str, Any]]] = None,
    ) -> None:
        super().__init__(bot, config)
        self.engine = TTSEngine(config=self.config)
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
                    try:
                        await vc.disconnect(force=True)
                    except Exception:
                        pass
                    await asyncio.sleep(float(self.config.disconnect_cleanup_delay))

            try:
                return await target_channel.connect(
                    reconnect=True,
                    timeout=float(self.config.voice_connect_timeout),
                )
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
        """Returns the configured TTS playback volume as float."""
        raw_vol = self.get_guild_setting(guild_id, "volume", self.config.volume)
        try:
            vol = float(raw_vol)
            max_float = float(self.config.volume_float_max)
            min_float = float(self.config.volume_float_min)
            if vol > max_float:
                vol = vol / 100.0
            return max(min_float, min(vol, max_float))
        except (ValueError, TypeError):
            return float(self.config.volume_float_fallback)

    def get_guild_speed(self, guild_id: Optional[int]) -> float:
        """Returns the configured speed multiplier for a guild."""
        val = self.get_guild_setting(guild_id, "voice_speed", float(self.config.voice_speed))
        try:
            return round(float(val), 1)
        except (ValueError, TypeError):
            return float(self.config.voice_speed)

    def get_guild_intro_delay(self, guild_id: Optional[int]) -> float:
        """Returns the configured delay in seconds before speech starts over the intro sound."""
        val = self.get_guild_setting(guild_id, "intro_delay", float(self.config.intro_delay))
        try:
            return round(float(val), 2)
        except (ValueError, TypeError):
            return round(float(self.config.intro_delay), 2)

    def _speed_to_rate(self, speed: float) -> str:
        """Converts speed multiplier (e.g. 1.0, 1.2, 0.8) to Edge-TTS rate string (+0%, +20%, -20%)."""
        percentage = round((speed - float(self.config.voice_speed)) * 100)
        sign = "+" if percentage >= 0 else ""
        return f"{sign}{percentage}%"

    def get_available_sounds(self) -> List[str]:
        """Scans the audio sounds directory and returns a sorted list of audio filenames."""
        sounds_dir = Path(self.config.sounds_dir)
        if not sounds_dir.exists():
            return []
        supported_exts = {ext.lower() for ext in self.config.supported_extensions}
        files = [
            f.name
            for f in sounds_dir.iterdir()
            if f.is_file() and f.suffix.lower() in supported_exts
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

    async def _voice_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> List[app_commands.Choice[str]]:
        choices = []
        for label, val in self.config.popular_voices:
            if current.lower() in label.lower() or current.lower() in val.lower():
                choices.append(app_commands.Choice(name=label, value=val))
        return choices[: int(self.config.max_autocomplete_choices)]

    async def _speed_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> List[app_commands.Choice[str]]:
        choices = []
        for label, val in self.config.speed_choices:
            if current.lower() in label.lower() or current.lower() in val.lower():
                choices.append(app_commands.Choice(name=label, value=val))
        return choices[: int(self.config.max_autocomplete_choices)]

    async def _delay_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> List[app_commands.Choice[str]]:
        choices = []
        for label, val in self.config.delay_choices:
            if current.lower() in label.lower() or current.lower() in val.lower():
                choices.append(app_commands.Choice(name=label, value=val))
        return choices[: int(self.config.max_autocomplete_choices)]

    async def _sound_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> List[app_commands.Choice[str]]:
        choices = [app_commands.Choice(name="None (Disabled)", value=str(self.config.intro_sound))]
        sounds = self.get_available_sounds()
        for s in sounds:
            if current.lower() in s.lower():
                clean_name = s.rsplit(".", 1)[0].replace("_", " ").title()
                choices.append(app_commands.Choice(name=f"{clean_name} ({s})", value=s))
        return choices[: int(self.config.max_autocomplete_choices)]

    tts_group = app_commands.Group(name="tts", description="Text-to-Speech service commands")

    async def _exec_speak(self, interaction: discord.Interaction, text: str):
        """Unified execution logic for speech synthesis and voice playback."""
        guild = interaction.guild
        if not guild:
            await interaction.response.send_message(
                "This command can only be used inside a server.", ephemeral=True
            )
            return

        await interaction.response.defer()

        vc = await self._connect_voice(interaction)
        if not vc:
            return

        max_len = int(self.get_guild_setting(guild.id, "max_text_length", self.config.max_text_length))
        filter_urls = bool(self.config.filter_urls)
        voice = str(self.get_guild_setting(guild.id, "voice", self.config.voice))

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

        intro_sound = str(self.get_guild_setting(guild.id, "intro_sound", str(self.config.intro_sound))).strip()
        if intro_sound and intro_sound.lower() != str(self.config.intro_sound):
            intro_path = Path(self.config.sounds_dir) / intro_sound
            if intro_path.exists():
                intro_delay = self.get_guild_intro_delay(guild.id)
                audio_path = await self.engine.mix_with_intro(
                    speech_path=audio_path,
                    intro_path=intro_path,
                    delay_seconds=intro_delay,
                )

        player = self.get_player(guild)
        preview_len = int(self.config.max_title_preview_length)
        title_text = (
            f"TTS: {cleaned_text[:preview_len]}"
            if len(cleaned_text) > preview_len
            else f"TTS: {cleaned_text}"
        )
        track = AudioTrack(
            title=title_text,
            source=audio_path,
            volume=self.get_service_volume(guild.id),
            volume_min=float(self.config.volume_float_min),
            volume_max=float(self.config.volume_float_max),
            service_name="tts",
            requester=interaction.user.display_name,
            channel=interaction.channel,
            text=cleaned_text,
            is_temporary=True,
        )

        pos = await player.add_track(track)
        if pos == 0:
            await interaction.followup.send(f"**{interaction.user.display_name}**: \"{cleaned_text}\"")
        else:
            await interaction.followup.send(
                f"Added to speech queue (#{pos}): \"{cleaned_text}\""
            )

    @tts_group.command(name="speak", description="Speaks text in current voice channel.")
    async def cmd_tts_speak(self, interaction: discord.Interaction, text: str):
        await self._exec_speak(interaction, text)

    def get_help_title(self) -> str:
        """Returns the formatted title for TTS help in embeds."""
        return "Text-to-Speech Commands (/tts)"

    def get_help_commands(self) -> List[tuple[str, str]]:
        """Returns the list of (command_syntax, description) for TTS service."""
        return [
            ("/tts speak <text>", "Synthesize and speak text in your voice channel"),
            ("/tts config", "View current server TTS configuration"),
            ("/tts set_voice <voice>", "Set default server voice (with autocomplete)"),
            ("/tts set_voice_speed <speed>", "Set speech speed (0.5x to 2.0x)"),
            ("/tts set_volume <volume>", "Set speech playback volume percentage (1-100)"),
            ("/tts set_max_text_length <length>", "Set maximum allowed text length for speech"),
            ("/tts set_intro <sound>", "Set intro sound cue before speech"),
            ("/tts set_intro_delay <delay>", "Set delay before speech begins over intro sound"),
            ("/tts set_channel [channel]", "Set automatic chat-to-speech channel"),
            ("/tts help", "Display this TTS command guide"),
        ]

    def get_help_embed(self) -> discord.Embed:
        """Returns a dedicated embed describing TTS commands."""
        embed = discord.Embed(
            title="Text-to-Speech Service Help",
            description="Available slash commands for Text-to-Speech synthesis. Type `/tts` in Discord to use autocomplete suggestions.",
            color=discord.Color.blue(),
        )
        commands_list = self.get_help_commands()
        lines = [f"• `{syntax}` - {desc}" for syntax, desc in commands_list]
        embed.add_field(
            name="Commands",
            value="\n".join(lines),
            inline=False,
        )
        embed.set_footer(text="Modular Discord Bot | Text-to-Speech Service")
        return embed

    @tts_group.command(name="help", description="Displays available commands and usage for the Text-to-Speech service.")
    async def cmd_tts_help(self, interaction: discord.Interaction):
        embed = self.get_help_embed()
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @tts_group.command(name="config", description="Shows current TTS configuration for this server.")
    async def cmd_tts_config(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            await interaction.response.send_message("Command only available in servers.", ephemeral=True)
            return

        voice = str(self.get_guild_setting(guild.id, "voice", str(self.config.voice)))
        speed = self.get_guild_speed(guild.id)
        intro_sound = self.get_guild_setting(guild.id, "intro_sound", str(self.config.intro_sound))
        intro_display = f"`{intro_sound}`" if intro_sound and intro_sound != str(self.config.intro_sound) else "None (disabled)"
        intro_delay = self.get_guild_intro_delay(guild.id)
        bound_ch_id = self.get_guild_setting(guild.id, "bound_channel_id")
        bound_ch_str = f"<#{bound_ch_id}>" if bound_ch_id else "None (uses `/tts speak` commands)"
        max_len = int(self.get_guild_setting(guild.id, "max_text_length", int(self.config.max_text_length)))
        vol_pct = int(self.get_service_volume(guild.id) * 100)

        vol_min, vol_max = self.get_numeric_bounds("volume")
        spd_min, spd_max = self.get_numeric_bounds("voice_speed")
        len_min, len_max = self.get_numeric_bounds("max_text_length")

        embed = discord.Embed(
            title=f"TTS Configuration - {guild.name}",
            color=discord.Color.blue(),
        )
        embed.add_field(name="Current Voice", value=f"`{voice}`", inline=True)
        embed.add_field(name="Speech Speed", value=f"`{speed:.1f}x` (range: {spd_min:.1f}-{spd_max:.1f}x)", inline=True)
        embed.add_field(name="Speech Volume", value=f"`{vol_pct}%` (range: {vol_min}-{vol_max}%)", inline=True)
        embed.add_field(name="Max Text Length", value=f"`{max_len}` chars (range: {len_min}-{len_max})", inline=True)
        embed.add_field(name="Intro Sound", value=intro_display, inline=True)
        embed.add_field(name="Intro Delay", value=f"`{intro_delay:.1f}s`", inline=True)
        embed.add_field(name="Auto-Reading Channel", value=bound_ch_str, inline=False)
        embed.add_field(
            name="Configuration Commands",
            value=(
                "• `/tts set_voice <voice>`: change server default voice\n"
                "• `/tts set_voice_speed <speed>`: adjust speech speed (e.g., `1.0x`, `1.2x`, `0.8x`)\n"
                "• `/tts set_volume <volume>`: adjust speech volume (1-100%)\n"
                "• `/tts set_max_text_length <length>`: set maximum text length for speech\n"
                "• `/tts set_intro <sound>`: choose sound cue played before message\n"
                "• `/tts set_intro_delay <delay>`: delay before speech starts over intro (e.g. `1.0s`)\n"
                "• `/tts set_channel [channel]`: set a text channel for automatic speech\n"
                "• `/tts config`: show this configuration overview\n"
                "• `/tts help`: display TTS commands help guide"
            ),
            inline=False,
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @tts_group.command(
        name="set_max_text_length",
        description="Sets the maximum text length allowed for TTS speech synthesis.",
    )
    @app_commands.describe(length="Maximum number of characters allowed per speech message")
    @app_commands.default_permissions(manage_guild=True)
    async def cmd_tts_set_max_text_length(self, interaction: discord.Interaction, length: int):
        guild = interaction.guild
        if not guild:
            await interaction.response.send_message("Command only available in servers.", ephemeral=True)
            return

        min_len, max_len = self.get_numeric_bounds("max_text_length")
        if length < min_len or length > max_len:
            await interaction.response.send_message(
                f"Max text length must be between {min_len} and {max_len} characters.",
                ephemeral=True,
            )
            return

        await self.set_guild_setting(guild.id, "max_text_length", length)
        await interaction.response.send_message(
            f"Maximum text length for TTS set to **{length} characters**."
        )

    @tts_group.command(name="set_voice", description="Sets the default neural TTS voice for this server.")
    @app_commands.describe(voice="Select the desired neural voice")
    @app_commands.autocomplete(voice=_voice_autocomplete)
    @app_commands.default_permissions(manage_guild=True)
    async def cmd_tts_set_voice(self, interaction: discord.Interaction, voice: str):
        if not interaction.guild:
            await interaction.response.send_message("Command only available in servers.", ephemeral=True)
            return

        await self.set_guild_setting(interaction.guild.id, "voice", voice)
        await interaction.response.send_message(
            f"Server voice successfully updated to: `{voice}`"
        )

    @tts_group.command(
        name="set_voice_speed",
        description="Sets the speech playback speed (starts at 1.0x, in 0.1x steps, e.g., 1.1x, 0.9x).",
    )
    @app_commands.describe(speed="Speed multiplier (e.g., 1.0x, 1.1x, 1.2x, 0.8x)")
    @app_commands.autocomplete(speed=_speed_autocomplete)
    @app_commands.default_permissions(manage_guild=True)
    async def cmd_tts_set_voice_speed(self, interaction: discord.Interaction, speed: str):
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

        min_spd, max_spd = self.get_numeric_bounds("voice_speed")
        if speed_val < min_spd or speed_val > max_spd:
            await interaction.response.send_message(
                f"Speed multiplier must be between `{min_spd:.1f}x` and `{max_spd:.1f}x` (with 0.1x steps).",
                ephemeral=True,
            )
            return

        await self.set_guild_setting(interaction.guild.id, "voice_speed", speed_val)
        await interaction.response.send_message(
            f"Speech speed successfully updated to: `{speed_val:.1f}x`"
        )

    @tts_group.command(
        name="set_intro",
        description="Sets a sound effect to play before each TTS message.",
    )
    @app_commands.describe(sound="Select an audio sound effect from data/sounds/ (or None)")
    @app_commands.autocomplete(sound=_sound_autocomplete)
    @app_commands.default_permissions(manage_guild=True)
    async def cmd_tts_set_intro(self, interaction: discord.Interaction, sound: str):
        if not interaction.guild:
            await interaction.response.send_message("Command only available in servers.", ephemeral=True)
            return

        sound_clean = sound.strip()
        if sound_clean.lower() in ("none", "disabled", "off"):
            await self.set_guild_setting(interaction.guild.id, "intro_sound", str(self.config.intro_sound))
            await interaction.response.send_message("Intro sound effect disabled.")
            return

        available = self.get_available_sounds()
        if sound_clean not in available:
            await interaction.response.send_message(
                f"Sound file `{sound_clean}` was not found in `{self.config.sounds_dir}/`. Use the autocomplete options.",
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

        min_delay, max_delay = self.get_numeric_bounds("intro_delay")
        if delay_val < min_delay or delay_val > max_delay:
            await interaction.response.send_message(
                f"Delay must be between `{min_delay:.1f}s` and `{max_delay:.1f}s`.",
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

        min_vol, max_vol = self.get_numeric_bounds("volume")
        if level < min_vol or level > max_vol:
            await interaction.response.send_message(
                f"Volume must be between {min_vol} and {max_vol}.",
                ephemeral=True,
            )
            return

        vol_float = level / 100.0
        await self.set_guild_setting(guild.id, "volume", level)

        player = self.get_player(guild)
        if player.current_track and player.current_track.service_name == "tts":
            player.set_current_volume(
                vol_float,
                volume_min=float(self.config.volume_float_min),
                volume_max=float(self.config.volume_float_max),
            )

        await interaction.response.send_message(f"TTS speech volume set to **{level}%**.")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """Reads messages sent in configured bound channel when bot is connected to voice."""
        if not message.guild:
            return
        if message.author.bot and not self.config.read_bot_messages:
            return

        prefix = self.bot.bot_config.prefix
        if message.content.startswith(prefix):
            return

        bound_channel_id = self.get_guild_setting(message.guild.id, "bound_channel_id")
        if not bound_channel_id or message.channel.id != bound_channel_id:
            return

        if message.attachments or message.stickers:
            return

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
            if not vc or not vc.is_connected():
                return

        max_len = int(self.get_guild_setting(message.guild.id, "max_text_length", self.config.max_text_length))
        filter_urls = bool(self.config.filter_urls)
        voice = str(self.get_guild_setting(message.guild.id, "voice", self.config.voice))

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

            intro_sound = str(self.get_guild_setting(message.guild.id, "intro_sound", str(self.config.intro_sound))).strip()
            if intro_sound and intro_sound.lower() != str(self.config.intro_sound):
                intro_path = Path(self.config.sounds_dir) / intro_sound
                if intro_path.exists():
                    intro_delay = self.get_guild_intro_delay(message.guild.id)
                    audio_path = await self.engine.mix_with_intro(
                        speech_path=audio_path,
                        intro_path=intro_path,
                        delay_seconds=intro_delay,
                    )

            player = self.get_player(message.guild)
            preview_len = int(self.config.max_title_preview_length)
            title_text = (
                f"TTS: {cleaned[:preview_len]}"
                if len(cleaned) > preview_len
                else f"TTS: {cleaned}"
            )
            track = AudioTrack(
                title=title_text,
                source=audio_path,
                volume=self.get_service_volume(message.guild.id),
                volume_min=float(self.config.volume_float_min),
                volume_max=float(self.config.volume_float_max),
                service_name="tts",
                requester=message.author.display_name,
                channel=message.channel,
                text=cleaned,
                is_temporary=True,
            )
            await player.add_track(track)
        except Exception as e:
            logger.error("Failed to synthesize automatic chat message in guild %s: %s", message.guild.id, e)
