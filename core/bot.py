from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import discord
from discord import app_commands
from discord.ext import commands

from core.guild_store import GuildStore
from core.service_manager import ServiceManager
from core.voice_queue import AudioTrack, GuildAudioPlayer

logger = logging.getLogger("bot.core")

TIMEOUT_CHOICES = [
    ("0s (Never disconnect)", 0),
    ("60s (1 minute)", 60),
    ("120s (2 minutes)", 120),
    ("180s (3 minutes)", 180),
    ("300s (5 minutes)", 300),
    ("600s (10 minutes)", 600),
]


class ModularBot(commands.Bot):
    """Modular Discord bot supporting independent pluggable services."""

    def __init__(self, config_path: str = "config/bot.json") -> None:
        self.bot_config = self._load_config(config_path)

        # Intents configuration
        intents = discord.Intents.default()
        intents.message_content = True
        intents.voice_states = True
        intents.guilds = True

        prefix = self.bot_config.get("prefix", "!")
        description = self.bot_config.get("description", "Modular Discord Bot")

        super().__init__(
            command_prefix=commands.when_mentioned_or(prefix),
            intents=intents,
            description=description,
            help_command=commands.DefaultHelpCommand(),
        )

        # Core components
        self.guild_store = GuildStore()
        self.service_manager = ServiceManager(self)
        self.audio_players: Dict[int, GuildAudioPlayer] = {}

    def get_audio_player(self, guild_id: int) -> GuildAudioPlayer:
        """Retrieves or creates the centralized audio player for a guild."""
        if guild_id not in self.audio_players:
            ffmpeg_path = self.bot_config.get("ffmpeg_path", "ffmpeg")
            self.audio_players[guild_id] = GuildAudioPlayer(
                guild_id=guild_id,
                bot=self,
                ffmpeg_path=ffmpeg_path,
            )
        return self.audio_players[guild_id]

    def _load_config(self, config_path: str) -> Dict[str, Any]:
        """Loads root bot configuration."""
        path = Path(config_path)
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error("Error loading %s: %s", config_path, e)
        return {"prefix": "!", "sync_commands_on_startup": True}

    def get_guild_timeout(self, guild_id: Optional[int]) -> int:
        """Returns configured inactivity timeout in seconds (0 = never disconnect)."""
        default_timeout = int(self.bot_config.get("auto_disconnect_timeout", 300))
        if guild_id is not None and hasattr(self, "guild_store"):
            custom_val = self.guild_store.get(guild_id, "bot", "auto_disconnect_timeout")
            if custom_val is None:
                custom_val = self.guild_store.get(guild_id, "tts", "auto_disconnect_timeout")
            if custom_val is not None:
                try:
                    return max(0, int(custom_val))
                except (ValueError, TypeError):
                    pass
        return max(0, default_timeout)

    async def set_guild_timeout(self, guild_id: int, timeout: int) -> None:
        """Saves custom inactivity timeout in seconds for a guild."""
        val = max(0, int(timeout))
        if hasattr(self, "guild_store"):
            await self.guild_store.set(guild_id, "bot", "auto_disconnect_timeout", val)
            if val == 0:
                player = self.audio_players.get(guild_id)
                if player:
                    player._cancel_idle_timer()

    async def setup_hook(self) -> None:
        """Asynchronous initialization hook before gateway login."""
        logger.info("Loading modular services...")
        await self.service_manager.load_all()

        # Register core and service management commands
        self._register_core_commands()

        # Synchronize Slash Commands if enabled
        if self.bot_config.get("sync_commands_on_startup", True):
            try:
                logger.info("Synchronizing application commands (Slash Commands)...")
                synced = await self.tree.sync()
                logger.info("%d application commands synchronized globally.", len(synced))
            except Exception as e:
                logger.error("Error syncing commands with Discord: %s", e)

    def _register_core_commands(self) -> None:
        """Registers core slash commands and service management under the /bot command group."""
        bot_group = app_commands.Group(
            name="bot",
            description="Core bot and voice management commands",
        )

        @bot_group.command(
            name="join",
            description="Connects the bot to your current voice channel.",
        )
        async def cmd_bot_join(interaction: discord.Interaction):
            guild = interaction.guild
            if not guild:
                await interaction.response.send_message("Command only available in servers.", ephemeral=True)
                return

            user = interaction.user
            if not isinstance(user, discord.Member) or not user.voice or not user.voice.channel:
                await interaction.response.send_message(
                    "You must join a voice channel before using this command.",
                    ephemeral=True,
                )
                return

            target_channel = user.voice.channel
            vc = guild.voice_client

            if vc and vc.is_connected():
                if vc.channel and vc.channel.id == target_channel.id:
                    await interaction.response.send_message(
                        f"Already connected to `{target_channel.name}`.",
                        ephemeral=True,
                    )
                    return
                try:
                    await vc.move_to(target_channel)
                    await interaction.response.send_message(f"Moved to voice channel `{target_channel.name}`.")
                    return
                except Exception as e:
                    logger.error("Failed to move to voice channel %s: %s", target_channel.id, e)
                    await interaction.response.send_message(f"Failed to move to `{target_channel.name}`: {e}", ephemeral=True)
                    return

            try:
                await target_channel.connect(reconnect=True, timeout=15.0)
                await interaction.response.send_message(f"Connected to voice channel `{target_channel.name}`.")
            except Exception as e:
                logger.error("Failed to connect to voice channel %s in guild %s: %s", target_channel.id, guild.id, e)
                await interaction.response.send_message(f"Failed to connect to voice channel: {e}", ephemeral=True)

        @bot_group.command(
            name="leave",
            description="Disconnects the bot from the voice channel and stops active playback.",
        )
        async def cmd_bot_leave(interaction: discord.Interaction):
            guild = interaction.guild
            if not guild:
                await interaction.response.send_message("Command only available in servers.", ephemeral=True)
                return

            vc = guild.voice_client
            if not vc or not vc.is_connected():
                await interaction.response.send_message("The bot is not connected to a voice channel.", ephemeral=True)
                return

            # Stop active playback and flush unified audio queue
            player = self.get_audio_player(guild.id)
            player.stop()

            ch_name = vc.channel.name if vc.channel else "voice"
            await vc.disconnect(force=True)
            await interaction.response.send_message(f"Disconnected from `{ch_name}` and stopped playback.")

        @bot_group.command(
            name="pause",
            description="Pauses current audio playback.",
        )
        async def cmd_bot_pause(interaction: discord.Interaction):
            guild = interaction.guild
            if not guild:
                await interaction.response.send_message("Command only available in servers.", ephemeral=True)
                return

            player = self.get_audio_player(guild.id)
            if player.pause():
                await interaction.response.send_message("Audio playback paused.")
            else:
                await interaction.response.send_message("Nothing is currently playing.", ephemeral=True)

        @bot_group.command(
            name="resume",
            description="Resumes paused audio playback.",
        )
        async def cmd_bot_resume(interaction: discord.Interaction):
            guild = interaction.guild
            if not guild:
                await interaction.response.send_message("Command only available in servers.", ephemeral=True)
                return

            player = self.get_audio_player(guild.id)
            if player.resume():
                await interaction.response.send_message("Audio playback resumed.")
            else:
                await interaction.response.send_message("Playback is not paused.", ephemeral=True)

        @bot_group.command(
            name="skip",
            description="Skips the currently playing audio track.",
        )
        async def cmd_bot_skip(interaction: discord.Interaction):
            guild = interaction.guild
            if not guild:
                await interaction.response.send_message("Command only available in servers.", ephemeral=True)
                return

            player = self.get_audio_player(guild.id)
            current = player.current_track
            if player.skip():
                title = current.title if current else "current audio"
                svc_tag = f" `[{current.service_name.upper()}]`" if (current and current.service_name) else ""
                await interaction.response.send_message(f"Skipped: **{title}**{svc_tag}")
            else:
                await interaction.response.send_message("No audio is currently playing to skip.", ephemeral=True)

        @bot_group.command(
            name="stop",
            description="Stops audio playback and clears the entire queue.",
        )
        async def cmd_bot_stop(interaction: discord.Interaction):
            guild = interaction.guild
            if not guild:
                await interaction.response.send_message("Command only available in servers.", ephemeral=True)
                return

            player = self.get_audio_player(guild.id)
            if not player.is_playing() and not player.is_paused() and not player.queue:
                await interaction.response.send_message("Nothing is currently playing.", ephemeral=True)
                return

            player.stop()
            await interaction.response.send_message("Playback stopped and audio queue cleared.")

        @bot_group.command(
            name="queue",
            description="Shows the current audio queue and active tracks across all services.",
        )
        async def cmd_bot_queue(interaction: discord.Interaction):
            guild = interaction.guild
            if not guild:
                await interaction.response.send_message("Command only available in servers.", ephemeral=True)
                return

            player = self.get_audio_player(guild.id)
            current = player.current_track
            queue_items = list(player.queue)

            if not current and not queue_items:
                await interaction.response.send_message("The audio queue is currently empty.", ephemeral=True)
                return

            embed = discord.Embed(
                title=f"Audio Queue - {guild.name}",
                color=discord.Color.blurple(),
            )

            if current:
                title_display = f"[{current.title}]({current.webpage_url})" if current.webpage_url else f"**{current.title}**"
                service_tag = f"`[{current.service_name.upper()}]`" if current.service_name else "`[CORE]`"
                duration = f" | `{current.formatted_duration}`" if current.duration and current.duration > 0 else ""
                req = f"\n*Requested by {current.requester}*" if current.requester else ""
                embed.add_field(
                    name="Currently Playing",
                    value=f"{service_tag} {title_display}{duration}{req}",
                    inline=False,
                )

            if queue_items:
                queue_str = ""
                for idx, item in enumerate(queue_items[:10], start=1):
                    item_title = f"[{item.title}]({item.webpage_url})" if item.webpage_url else f"**{item.title}**"
                    svc_tag = f"`[{item.service_name.upper()}]`" if item.service_name else "`[CORE]`"
                    duration = f" | `{item.formatted_duration}`" if item.duration and item.duration > 0 else ""
                    req = f" ({item.requester})" if item.requester else ""
                    queue_str += f"`{idx}.` {svc_tag} {item_title}{duration}{req}\n"

                if len(queue_items) > 10:
                    queue_str += f"\n*... and {len(queue_items) - 10} more track(s)*"

                embed.add_field(
                    name=f"Up Next ({len(queue_items)} track(s))",
                    value=queue_str,
                    inline=False,
                )
            else:
                embed.add_field(name="Up Next", value="*No upcoming audio in queue*", inline=False)

            await interaction.response.send_message(embed=embed)

        # Autocomplete for timeout command
        async def _timeout_autocomplete(
            interaction: discord.Interaction, current: str
        ) -> List[app_commands.Choice[int]]:
            choices = []
            for label, val in TIMEOUT_CHOICES:
                if current.lower() in label.lower() or current in str(val):
                    choices.append(app_commands.Choice(name=label, value=val))
            return choices[:25]

        @bot_group.command(
            name="set_auto_disconnect_timeout",
            description="Sets or views the bot voice inactivity disconnect timeout in seconds (0 = never disconnect).",
        )
        @app_commands.describe(seconds="Inactivity timeout in seconds (0 = never disconnect, leave empty to view)")
        @app_commands.autocomplete(seconds=_timeout_autocomplete)
        @app_commands.default_permissions(manage_guild=True)
        async def cmd_bot_timeout(interaction: discord.Interaction, seconds: Optional[int] = None):
            guild = interaction.guild
            if not guild:
                await interaction.response.send_message("Command only available in servers.", ephemeral=True)
                return

            if seconds is None:
                current_timeout = self.get_guild_timeout(guild.id)
                if current_timeout == 0:
                    msg = "Current voice inactivity timeout: Never (disabled). The bot will stay connected indefinitely."
                else:
                    msg = f"Current voice inactivity timeout: {current_timeout}s ({current_timeout // 60}m)."
                await interaction.response.send_message(msg, ephemeral=True)
                return

            if seconds < 0:
                await interaction.response.send_message("Timeout cannot be negative. Use 0 to disable auto-disconnect.", ephemeral=True)
                return

            await self.set_guild_timeout(guild.id, seconds)

            if seconds == 0:
                msg = "Auto-disconnect disabled! The bot will never leave the voice channel due to inactivity."
            else:
                msg = f"Inactivity timeout set to {seconds}s! The bot will disconnect after {seconds} seconds of silence."
            await interaction.response.send_message(msg)

        # Services management subgroup: /bot services <list|reload>
        services_group = app_commands.Group(
            name="services",
            description="Commands for managing modular bot services",
            parent=bot_group,
            default_permissions=discord.Permissions(administrator=True),
        )

        @services_group.command(name="list", description="Lists all discovered services and their statuses.")
        async def list_services(interaction: discord.Interaction):
            discovered = self.service_manager.discover_services()
            if not discovered:
                await interaction.response.send_message("No services found in `services/` directory.", ephemeral=True)
                return

            embed = discord.Embed(
                title="Modular Services",
                description="Status of services available in the bot:",
                color=discord.Color.blurple(),
            )

            for s_name in discovered:
                is_loaded = s_name in self.service_manager.services
                cfg = self.service_manager.load_service_config(s_name)
                is_enabled = cfg.get("enabled", True)

                status_tag = "[ACTIVE]" if is_loaded else ("[ENABLED]" if is_enabled else "[DISABLED]")
                status_txt = "Active" if is_loaded else ("Enabled (not loaded)" if is_enabled else "Disabled in config")

                embed.add_field(
                    name=f"{status_tag} {s_name}",
                    value=f"Status: **{status_txt}**\nConfig: `config/{s_name}.json`",
                    inline=False,
                )

            await interaction.response.send_message(embed=embed, ephemeral=True)

        @services_group.command(name="reload", description="Reloads a specific service.")
        @app_commands.describe(service="Name of the service to reload")
        async def reload_service(interaction: discord.Interaction, service: str):
            await interaction.response.defer(ephemeral=True)
            success = await self.service_manager.reload_service(service)
            if success:
                try:
                    await self.tree.sync()
                except Exception:
                    pass
                await interaction.followup.send(f"Service `{service}` reloaded successfully!", ephemeral=True)
            else:
                await interaction.followup.send(f"Failed to reload service `{service}`. Check console logs.", ephemeral=True)

        self.tree.add_command(bot_group)

        # Traditional prefix command for instant guild synchronization (!sync)
        @self.command(name="sync")
        @commands.has_permissions(administrator=True)
        async def sync_commands_command(ctx: commands.Context):
            """Synchronizes slash commands globally and clears any duplicate guild-scoped commands."""
            if not ctx.guild:
                await ctx.send("This command can only be used in a server.")
                return

            status_msg = await ctx.send("Synchronizing global commands and clearing guild duplicates...")
            try:
                # Clear guild-specific commands to prevent duplicate commands in autocomplete
                self.tree.clear_commands(guild=ctx.guild)
                await self.tree.sync(guild=ctx.guild)

                # Synchronize globally
                synced = await self.tree.sync()
                await status_msg.edit(
                    content=f"{len(synced)} slash commands synchronized globally without duplicates! (Press Ctrl+R in Discord to refresh your UI cache)"
                )
            except Exception as e:
                await status_msg.edit(content=f"Error syncing commands: {e}")

    async def on_ready(self) -> None:
        status_msg = self.bot_config.get("status_message", "/tts speak | /yt play")
        await self.change_presence(activity=discord.Activity(type=discord.ActivityType.listening, name=status_msg))
        logger.info("Bot connected as %s (ID: %s)", self.user, self.user.id if self.user else "N/A")
        logger.info("Connected to %d guild(s)", len(self.guilds))

        # Clear any guild-scoped commands to prevent Discord from showing duplicate global + guild commands in autocomplete
        for guild in self.guilds:
            try:
                self.tree.clear_commands(guild=guild)
                await self.tree.sync(guild=guild)
                logger.info("Cleaned guild-specific commands for %s (%s) to prevent autocomplete duplicates.", guild.name, guild.id)
            except Exception as e:
                logger.error("Failed to clean guild commands for %s: %s", guild.id, e)

