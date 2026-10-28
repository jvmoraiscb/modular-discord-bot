"""Soundboard audio effects service using local files and Discord voice."""
from __future__ import annotations

import logging
from pathlib import Path
import re
from typing import Any, ClassVar, Dict, List, Optional, Set, TYPE_CHECKING, Type, Union

import discord
from discord import app_commands

from core.service_base import BaseService
from core.voice_queue import AudioTrack, GuildAudioPlayer
from services.sounds.models import SoundsConfig, SoundsGuildConfig

if TYPE_CHECKING:
    from core.bot import ModularBot

logger = logging.getLogger("bot.service.sounds")


class SoundsService(BaseService[SoundsConfig, SoundsGuildConfig]):
    """Soundboard audio effects playback and file management service."""

    name: str = "sounds"
    description: str = "Soundboard effects playback and management service"
    config_class: ClassVar[Type[SoundsConfig]] = SoundsConfig
    guild_config_class: ClassVar[Type[SoundsGuildConfig]] = SoundsGuildConfig

    def __init__(
        self,
        bot: ModularBot,
        config: Optional[Union[SoundsConfig, Dict[str, Any]]] = None,
    ) -> None:
        super().__init__(bot, config)
        self.sounds_dir = self.get_sounds_dir()
        self.sound_name_regex = re.compile(self.config.sound_name_pattern)

    def get_sounds_dir(self) -> Path:
        """Returns the configured sounds directory path, creating it if needed."""
        dir_path = Path(self.config.sounds_dir)
        dir_path.mkdir(parents=True, exist_ok=True)
        return dir_path

    def get_supported_extensions(self) -> Set[str]:
        """Returns the set of supported audio file extensions."""
        return {ext.lower() for ext in self.config.supported_extensions}

    def get_available_sounds(self) -> List[Path]:
        """Returns a sorted list of all valid audio files in the sounds directory."""
        dir_path = self.get_sounds_dir()
        if not dir_path.exists():
            return []

        supported = self.get_supported_extensions()
        files = [
            f for f in dir_path.iterdir()
            if f.is_file() and f.suffix.lower() in supported
        ]
        return sorted(files, key=lambda p: p.stem.lower())

    def find_sound(self, name: str) -> Optional[Path]:
        """Finds a sound file by its stem or full filename."""
        clean_name = name.strip().lower()
        for sound_file in self.get_available_sounds():
            if sound_file.stem.lower() == clean_name or sound_file.name.lower() == clean_name:
                return sound_file
        return None

    def get_service_volume(self, guild_id: Optional[int]) -> float:
        """Returns the configured sound playback volume as a float."""
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

    def get_player(self, guild: discord.Guild) -> GuildAudioPlayer:
        """Retrieves the unified audio player for this guild from the bot core."""
        return self.bot.get_audio_player(guild.id)

    async def _connect_voice(self, interaction: discord.Interaction) -> Optional[discord.VoiceClient]:
        """Connects or moves the bot to the invoking user's voice channel."""
        user = interaction.user
        if not isinstance(user, discord.Member) or not user.voice or not user.voice.channel:
            if interaction.response.is_done():
                await interaction.followup.send(
                    "You must join a voice channel before using this command.",
                    ephemeral=True,
                )
            else:
                await interaction.response.send_message(
                    "You must join a voice channel before using this command.",
                    ephemeral=True,
                )
            return None

        target_channel = user.voice.channel
        guild = interaction.guild
        if not guild:
            return None

        vc = guild.voice_client

        if vc:
            if vc.is_connected():
                if vc.channel and vc.channel.id != target_channel.id:
                    try:
                        await vc.move_to(target_channel)
                    except Exception as e:
                        logger.error("Failed to move to voice channel %s in guild %s: %s", target_channel.id, guild.id, e)
                return vc
            else:
                try:
                    await vc.disconnect(force=True)
                except Exception:
                    pass

        try:
            connect_timeout = float(self.config.voice_connect_timeout)
            return await target_channel.connect(reconnect=True, timeout=connect_timeout)
        except discord.ClientException:
            vc = guild.voice_client
            if vc and vc.channel and vc.channel.id != target_channel.id:
                try:
                    await vc.move_to(target_channel)
                except Exception:
                    pass
            return vc
        except Exception as e:
            logger.error("Failed to connect to voice channel %s in guild %s: %s", target_channel.id, guild.id, e)
            msg = f"Failed to connect to `{target_channel.name}`: {e}"
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
            return None

    async def autocomplete_sound_name(
        self, interaction: discord.Interaction, current: str
    ) -> List[app_commands.Choice[str]]:
        """Autocomplete handler suggesting available audio files from data/sounds/."""
        sounds = self.get_available_sounds()
        current_lower = current.strip().lower()
        choices: List[app_commands.Choice[str]] = []
        max_choices = int(self.config.max_autocomplete_choices)

        for s in sounds:
            if current_lower in s.stem.lower() or current_lower in s.name.lower():
                choices.append(app_commands.Choice(name=s.stem, value=s.stem))
                if len(choices) >= max_choices:
                    break

        return choices

    sounds_group = app_commands.Group(name="sounds", description="Soundboard audio effects playback and management")

    @sounds_group.command(name="play", description="Plays an audio effect in your voice channel.")
    @app_commands.describe(sound="Name of the sound to play")
    @app_commands.autocomplete(sound=autocomplete_sound_name)
    async def cmd_play(self, interaction: discord.Interaction, sound: str):
        guild = interaction.guild
        if not guild:
            await interaction.response.send_message("Command only available in servers.", ephemeral=True)
            return

        sound_file = self.find_sound(sound)
        if not sound_file:
            await interaction.response.send_message(
                f"Sound `{sound}` not found. Use `/sounds list` to view all available sounds.",
                ephemeral=True,
            )
            return

        vc = await self._connect_voice(interaction)
        if not vc:
            return

        player = self.get_player(guild)
        track = AudioTrack(
            title=f"Sound: {sound_file.stem}",
            source=str(sound_file.resolve()),
            volume=self.get_service_volume(guild.id),
            volume_min=float(self.config.volume_float_min),
            volume_max=float(self.config.volume_float_max),
            service_name="sounds",
            requester=interaction.user.display_name,
            channel=interaction.channel,
            is_temporary=False,
        )

        pos = await player.add_track(track)
        if pos == 0:
            await interaction.response.send_message(f"Playing sound: **{sound_file.stem}**")
        else:
            await interaction.response.send_message(f"Added to queue (#{pos}): **{sound_file.stem}**")

    @sounds_group.command(name="list", description="Lists all available audio files in data/sounds/.")
    async def cmd_list(self, interaction: discord.Interaction):
        sounds = self.get_available_sounds()
        if not sounds:
            await interaction.response.send_message(
                f"No sound files found in `{self.config.sounds_dir}/`.\n"
                "Use `/sounds add <name> <file>` to upload your first audio file.",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title=f"Soundboard Library ({len(sounds)} sounds)",
            description="Use `/sounds play <name>` to play any sound in your voice channel.",
            color=discord.Color.green(),
        )

        max_page = int(self.config.max_sounds_per_page)
        lines: List[str] = []
        for s in sounds[:max_page]:
            size_kb = s.stat().st_size / 1024.0
            if size_kb >= 1024:
                size_str = f"{size_kb / 1024.0:.1f} MB"
            else:
                size_str = f"{size_kb:.1f} KB"
            lines.append(f"• **{s.stem}** (`{s.suffix}`, {size_str})")

        embed.add_field(name="Available Sounds", value="\n".join(lines), inline=False)
        if len(sounds) > max_page:
            embed.set_footer(text=f"Showing first {max_page} of {len(sounds)} sounds")
        else:
            embed.set_footer(text="Modular Discord Bot | Soundboard Service")

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @sounds_group.command(
        name="add",
        description="Uploads and saves a new sound file to data/sounds/.",
    )
    @app_commands.describe(
        name="Unique identifier name for the sound (e.g. airhorn, boom)",
        file="Audio file to upload (.mp3, .wav, .ogg, .m4a)",
    )
    async def cmd_add(self, interaction: discord.Interaction, name: str, file: discord.Attachment):
        clean_name = name.strip().lower()

        if not self.sound_name_regex.match(clean_name):
            await interaction.response.send_message(
                "Invalid sound name! Only alphanumeric characters, dashes, and underscores are allowed (e.g. `airhorn`, `my_sound-1`).",
                ephemeral=True,
            )
            return

        max_name_len = int(self.config.max_name_length)
        if len(clean_name) > max_name_len:
            await interaction.response.send_message(
                f"Sound name is too long! Maximum length is {max_name_len} characters.",
                ephemeral=True,
            )
            return

        supported = self.get_supported_extensions()
        file_ext = Path(file.filename).suffix.lower()
        if file_ext not in supported:
            allowed_str = ", ".join(sorted(supported))
            await interaction.response.send_message(
                f"Unsupported file format `{file_ext}`! Supported formats: {allowed_str}",
                ephemeral=True,
            )
            return

        max_bytes = int(self.config.max_file_size_bytes)
        if file.size > max_bytes:
            max_mb = max_bytes / (1024 * 1024)
            await interaction.response.send_message(
                f"File is too large! Maximum allowed size is {max_mb:.0f} MB.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        target_path = self.get_sounds_dir() / f"{clean_name}{file_ext}"
        try:
            await file.save(target_path)
            size_kb = file.size / 1024.0
            await interaction.followup.send(
                f"Sound **{clean_name}** ({size_kb:.1f} KB) added successfully!\n"
                f"You can now play it using `/sounds play sound:{clean_name}`.",
                ephemeral=True,
            )
            logger.info("Sound '%s' saved to %s by user %s", clean_name, target_path, interaction.user)
        except Exception as e:
            logger.error("Failed to save uploaded sound '%s': %s", clean_name, e)
            await interaction.followup.send(
                f"Failed to save sound: {e}",
                ephemeral=True,
            )

    @sounds_group.command(name="set_volume", description="Sets default soundboard playback volume (1-100%).")
    @app_commands.describe(level="Volume level from 1 to 100")
    async def cmd_set_volume(self, interaction: discord.Interaction, level: int):
        guild = interaction.guild
        if not guild:
            await interaction.response.send_message("Command only available in servers.", ephemeral=True)
            return

        vol_min, vol_max = self.get_numeric_bounds("volume")
        if level < vol_min or level > vol_max:
            await interaction.response.send_message(
                f"Volume must be between {vol_min} and {vol_max}.",
                ephemeral=True,
            )
            return

        player = self.get_player(guild)
        vol_float = level / 100.0
        if player.current_track and player.current_track.service_name == "sounds":
            player.set_current_volume(
                vol_float,
                volume_min=float(self.config.volume_float_min),
                volume_max=float(self.config.volume_float_max),
            )
        await self.set_guild_setting(guild.id, "volume", level)

        await interaction.response.send_message(f"Soundboard volume set to **{level}%**.")

    def get_help_title(self) -> str:
        """Returns the formatted title for soundboard commands in help embeds."""
        return "Soundboard Commands (/sounds)"

    def get_help_commands(self) -> List[tuple[str, str]]:
        """Returns the list of (command_syntax, description) for sounds service."""
        return [
            ("/sounds play <sound>", "Play an audio sound effect in your voice channel"),
            ("/sounds list", f"List all available sound effects in {self.config.sounds_dir}/"),
            ("/sounds add <name> <file>", f"Upload and save a new audio file to {self.config.sounds_dir}/"),
            ("/sounds set_volume <1-100>", "Set default playback volume percentage for this server"),
            ("/sounds help", "Display soundboard commands help guide"),
        ]

    def get_help_embed(self) -> discord.Embed:
        """Returns a dedicated embed describing soundboard commands."""
        embed = discord.Embed(
            title="Soundboard Service Help",
            description="Available slash commands for the Soundboard service. Type `/sounds` in Discord to use autocomplete suggestions.",
            color=discord.Color.green(),
        )
        commands_list = self.get_help_commands()
        lines = [f"• `{syntax}` - {desc}" for syntax, desc in commands_list]
        embed.add_field(
            name="Commands",
            value="\n".join(lines),
            inline=False,
        )
        embed.set_footer(text="Modular Discord Bot | Soundboard Service")
        return embed

    @sounds_group.command(name="help", description="Displays available commands and usage for the soundboard service.")
    async def cmd_sounds_help(self, interaction: discord.Interaction):
        embed = self.get_help_embed()
        await interaction.response.send_message(embed=embed, ephemeral=True)
