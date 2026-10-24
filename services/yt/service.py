from __future__ import annotations
import logging
from typing import Dict, Optional

import discord
from discord import app_commands

from core.service_base import BaseService
from core.voice_queue import AudioTrack, GuildAudioPlayer
from services.yt.ytdl_player import Song, YTDLExtractor, format_duration

logger = logging.getLogger("bot.service.yt")


class YTService(BaseService):
    """YouTube music streaming and playlist queue management service."""

    name: str = "yt"
    description: str = "YouTube audio streaming and playlist queue management"

    def __init__(self, bot, config: Optional[dict] = None) -> None:
        super().__init__(bot, config)
        self.extractor = YTDLExtractor()

    def get_player(self, guild: discord.Guild) -> GuildAudioPlayer:
        """Retrieves the unified audio player for this guild from the bot core."""
        return self.bot.get_audio_player(guild.id)

    def get_service_volume(self, guild_id: Optional[int]) -> float:
        """Returns the configured YouTube playback volume as float (0.0 - 2.0)."""
        raw_vol = self.get_guild_setting(
            guild_id, "default_volume", self.config.get("default_volume", 10)
        )
        try:
            vol = float(raw_vol)
            if vol > 2.0:
                vol = vol / 100.0
            return max(0.0, min(vol, 2.0))
        except (ValueError, TypeError):
            return 0.1

    async def on_service_unload(self) -> None:
        """Cleans up active music service upon unloading."""
        pass

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
            return await target_channel.connect(reconnect=True, timeout=15.0)
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
            if interaction.response.is_done():
                await interaction.followup.send(
                    f"Failed to connect to `{target_channel.name}`: {e}",
                    ephemeral=True,
                )
            else:
                await interaction.response.send_message(
                    f"Failed to connect to `{target_channel.name}`: {e}",
                    ephemeral=True,
                )
            return None

    # --- /yt COMMAND GROUP ---
    yt_group = app_commands.Group(name="yt", description="YouTube music playback and queue commands")

    @yt_group.command(name="play", description="Plays audio from a YouTube link or search query.")
    @app_commands.describe(query="YouTube video URL or search keywords")
    async def cmd_play(self, interaction: discord.Interaction, query: str):
        guild = interaction.guild
        if not guild:
            await interaction.response.send_message("Command only available in servers.", ephemeral=True)
            return

        # Defer response as audio extraction can take a second
        await interaction.response.defer()

        vc = await self._connect_voice(interaction)
        if not vc:
            return

        player = self.get_player(guild)
        song = await self.extractor.extract_song(
            query=query,
            requester=interaction.user.display_name,
            loop=self.bot.loop,
        )

        if not song:
            await interaction.followup.send(f"Could not find or extract audio for: `{query}`")
            return

        track = AudioTrack(
            title=song.title,
            source=song.stream_url,
            volume=self.get_service_volume(guild.id),
            service_name="yt",
            requester=song.requester,
            channel=interaction.channel,
            duration=song.duration,
            thumbnail=song.thumbnail,
            uploader=song.uploader,
            webpage_url=song.webpage_url,
            is_temporary=False,
        )

        pos = await player.add_track(track)

        embed = discord.Embed(
            color=discord.Color.red(),
            title=song.title,
            url=song.webpage_url,
        )
        if song.thumbnail:
            embed.set_thumbnail(url=song.thumbnail)
        embed.add_field(name="Channel", value=song.uploader, inline=True)
        embed.add_field(name="Duration", value=song.formatted_duration, inline=True)
        embed.set_footer(
            text=f"Requested by {interaction.user.display_name}",
            icon_url=interaction.user.display_avatar.url if interaction.user.display_avatar else None,
        )

        if pos == 0:
            embed.description = "**Now playing**"
            await interaction.followup.send(embed=embed)
        else:
            embed.description = f"**Added to queue (#{pos})**"
            await interaction.followup.send(embed=embed)

    @yt_group.command(name="set_volume", description="Sets music playback volume (1-100%).")
    @app_commands.describe(level="Volume level from 1 to 100")
    async def cmd_set_volume(self, interaction: discord.Interaction, level: int):
        guild = interaction.guild
        if not guild:
            await interaction.response.send_message("Command only available in servers.", ephemeral=True)
            return

        if level < 1 or level > 100:
            await interaction.response.send_message("Volume must be between 1 and 100.", ephemeral=True)
            return

        player = self.get_player(guild)
        vol_float = level / 100.0
        player.set_current_volume(vol_float)
        await self.set_guild_setting(guild.id, "default_volume", level)

        await interaction.response.send_message(f"Playback volume set to **{level}%**.")

