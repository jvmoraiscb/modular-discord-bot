from __future__ import annotations
import logging
from typing import Dict, Optional

import discord
from discord import app_commands

from core.service_base import BaseService
from services.yt.music_queue import GuildMusicPlayer
from services.yt.ytdl_player import Song, YTDLExtractor, format_duration

logger = logging.getLogger("bot.service.yt")


class YTService(BaseService):
    """YouTube music streaming and playlist queue management service."""

    name: str = "yt"
    description: str = "YouTube audio streaming and playlist queue management"

    def __init__(self, bot, config: Optional[dict] = None) -> None:
        super().__init__(bot, config)
        self.extractor = YTDLExtractor()
        self.players: Dict[int, GuildMusicPlayer] = {}

    def get_player(self, guild: discord.Guild) -> GuildMusicPlayer:
        """Retrieves or creates the GuildMusicPlayer instance for a guild."""
        if guild.id not in self.players:
            vol_pct = int(self.get_guild_setting(guild.id, "default_volume", 100))
            idle_timeout = self.bot.get_guild_timeout(guild.id) if hasattr(self.bot, "get_guild_timeout") else 300
            ffmpeg_path = str(self.get_guild_setting(guild.id, "ffmpeg_path", "ffmpeg"))

            self.players[guild.id] = GuildMusicPlayer(
                guild=guild,
                bot=self.bot,
                volume=vol_pct / 100.0,
                idle_timeout=idle_timeout,
                ffmpeg_path=ffmpeg_path,
            )
        return self.players[guild.id]

    async def on_service_unload(self) -> None:
        """Cleans up active music players when service is unloaded."""
        for player in self.players.values():
            player.stop()
            player._cancel_idle_timer()
        self.players.clear()

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

        pos = await player.add_song(song, channel=interaction.channel)

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

    @yt_group.command(name="pause", description="Pauses current music playback.")
    async def cmd_pause(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            await interaction.response.send_message("Command only available in servers.", ephemeral=True)
            return

        player = self.get_player(guild)
        if player.pause():
            await interaction.response.send_message("Music playback paused.")
        else:
            await interaction.response.send_message("Nothing is currently playing.", ephemeral=True)

    @yt_group.command(name="resume", description="Resumes paused music playback.")
    async def cmd_resume(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            await interaction.response.send_message("Command only available in servers.", ephemeral=True)
            return

        player = self.get_player(guild)
        if player.resume():
            await interaction.response.send_message("Music playback resumed.")
        else:
            await interaction.response.send_message("Playback is not paused.", ephemeral=True)

    @yt_group.command(name="skip", description="Skips the currently playing song.")
    async def cmd_skip(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            await interaction.response.send_message("Command only available in servers.", ephemeral=True)
            return

        player = self.get_player(guild)
        current = player.current_song
        if player.skip():
            title = current.title if current else "current song"
            await interaction.response.send_message(f"Skipped: **{title}**")
        else:
            await interaction.response.send_message("No song is currently playing.", ephemeral=True)

    @yt_group.command(name="stop", description="Stops music playback and clears the queue.")
    async def cmd_stop(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            await interaction.response.send_message("Command only available in servers.", ephemeral=True)
            return

        player = self.get_player(guild)
        player.stop()
        await interaction.response.send_message("Playback stopped and queue cleared.")

    @yt_group.command(name="queue", description="Shows the current song queue.")
    async def cmd_queue(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            await interaction.response.send_message("Command only available in servers.", ephemeral=True)
            return

        player = self.get_player(guild)
        current = player.current_song
        queue_items = list(player.queue)

        if not current and not queue_items:
            await interaction.response.send_message("The music queue is currently empty.", ephemeral=True)
            return

        embed = discord.Embed(
            title=f"Music Queue - {guild.name}",
            color=discord.Color.red(),
        )

        if current:
            embed.add_field(
                name="Currently Playing",
                value=f"[{current.title}]({current.webpage_url}) | `{current.formatted_duration}`\n*Requested by {current.requester}*",
                inline=False,
            )

        if queue_items:
            queue_str = ""
            for idx, item in enumerate(queue_items[:10], start=1):
                queue_str += f"`{idx}.` [{item.title}]({item.webpage_url}) | `{item.formatted_duration}` ({item.requester})\n"

            if len(queue_items) > 10:
                queue_str += f"\n*... and {len(queue_items) - 10} more track(s)*"

            embed.add_field(
                name=f"Up Next ({len(queue_items)} track(s))",
                value=queue_str,
                inline=False,
            )
        else:
            embed.add_field(name="Up Next", value="*No upcoming songs in queue*", inline=False)

        await interaction.response.send_message(embed=embed)

    @yt_group.command(name="nowplaying", description="Shows details about the currently playing song.")
    async def cmd_nowplaying(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            await interaction.response.send_message("Command only available in servers.", ephemeral=True)
            return

        player = self.get_player(guild)
        song = player.current_song

        if not song:
            await interaction.response.send_message("No song is currently playing.", ephemeral=True)
            return

        embed = discord.Embed(
            title=song.title,
            url=song.webpage_url,
            color=discord.Color.red(),
            description="**Currently Playing**",
        )
        if song.thumbnail:
            embed.set_thumbnail(url=song.thumbnail)
        embed.add_field(name="Channel", value=song.uploader, inline=True)
        embed.add_field(name="Duration", value=song.formatted_duration, inline=True)
        embed.add_field(name="Volume", value=f"{int(player.volume * 100)}%", inline=True)
        embed.set_footer(text=f"Requested by {song.requester}")

        await interaction.response.send_message(embed=embed)

    @yt_group.command(name="volume", description="Sets music playback volume (1-100%).")
    @app_commands.describe(level="Volume level from 1 to 100")
    async def cmd_volume(self, interaction: discord.Interaction, level: int):
        guild = interaction.guild
        if not guild:
            await interaction.response.send_message("Command only available in servers.", ephemeral=True)
            return

        if level < 1 or level > 100:
            await interaction.response.send_message("Volume must be between 1 and 100.", ephemeral=True)
            return

        player = self.get_player(guild)
        player.set_volume(level / 100.0)
        await self.set_guild_setting(guild.id, "default_volume", level)

        await interaction.response.send_message(f"Playback volume set to **{level}%**.")

