import importlib
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

import discord
from discord import app_commands
from discord.ext import commands

if TYPE_CHECKING:
    from core.bot import ModularBot


class BaseService(commands.Cog):
    """Base class for all pluggable bot services.

    Each service has:
    - Dedicated default configuration in `config/<service_name>.json`.
    - Transparent access to custom per-guild settings.
    - Lifecycle hooks (on_service_load / on_service_unload).
    """

    name: str = "base_service"

    def __init__(self, bot: ModularBot, config: Optional[Dict[str, Any]] = None) -> None:
        self.bot = bot
        defaults = self.load_defaults()
        self.config = {**defaults, **(config or {})}
        self.logger = logging.getLogger(f"bot.service.{self.name}")

    def load_defaults(self) -> Dict[str, Any]:
        """Loads default configuration for this service from its defaults module if available."""
        try:
            defaults_mod = importlib.import_module(f"services.{self.name}.defaults")
            if hasattr(defaults_mod, "get_default_config"):
                return defaults_mod.get_default_config()
        except Exception:
            pass
        return {}

    def get_config_path(self) -> Path:
        """Returns the configuration file path for this service."""
        return Path(f"config/{self.name}.json")

    def save_config(self) -> None:
        """Saves default service configuration to disk."""
        path = self.get_config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
            self.logger.info("Default configuration for service '%s' successfully saved.", self.name)
        except Exception as e:
            self.logger.error("Failed to save configuration for '%s': %s", self.name, e)

    def get_guild_setting(self, guild_id: Optional[int], key: str, default: Any = None) -> Any:
        """Retrieves a configuration value for the specified guild.

        If the guild has a saved custom override, that value is returned.
        Otherwise, it falls back to the default value from config/<service>.json.
        """
        if guild_id is not None and hasattr(self.bot, "guild_store"):
            custom_val = self.bot.guild_store.get(guild_id, self.name, key)
            if custom_val is not None:
                return custom_val

        # Fallback to service default config
        return self.config.get(key, default)

    async def set_guild_setting(self, guild_id: int, key: str, value: Any) -> None:
        """Saves a custom configuration value for a guild."""
        if hasattr(self.bot, "guild_store"):
            await self.bot.guild_store.set(guild_id, self.name, key, value)

    def get_numeric_bounds(
        self, key: str, default_min: float | int, default_max: float | int
    ) -> tuple[Any, Any]:
        """Retrieves static (min, max) limits defined directly in the service configuration.

        These limits are defined at the service configuration level and cannot be overridden per guild.
        """
        min_val = self.config.get(f"{key}_min", self.config.get(f"min_{key}", default_min))
        max_val = self.config.get(f"{key}_max", self.config.get(f"max_{key}", default_max))
        if isinstance(default_min, int) and isinstance(default_max, int):
            try:
                return int(min_val), int(max_val)
            except (ValueError, TypeError):
                return default_min, default_max
        try:
            return float(min_val), float(max_val)
        except (ValueError, TypeError):
            return float(default_min), float(default_max)

    def get_effective_config(self, guild_id: Optional[int]) -> Dict[str, Any]:
        """Returns the complete effective configuration for a guild (defaults merged with overrides)."""
        effective = dict(self.config)
        if guild_id is not None and hasattr(self.bot, "guild_store"):
            guild_overrides = self.bot.guild_store.get_service_settings(guild_id, self.name)
            effective.update(guild_overrides)
        return effective

    def get_help_title(self) -> str:
        """Returns the formatted title for this service's command section in help menus."""
        return f"{self.name.upper()} Commands (/{self.name})"

    def get_help_commands(self) -> List[tuple[str, str]]:
        """Returns a list of (syntax, description) tuples for the service commands.

        Subclasses can override this to provide custom descriptions or ordered lists.
        By default, it dynamically introspects any app_commands.Group attached to the Cog.
        """
        commands_list: List[tuple[str, str]] = []
        for attr_name in dir(self):
            attr = getattr(self, attr_name, None)
            if isinstance(attr, app_commands.Group):
                for cmd in attr.commands:
                    params = " ".join(f"<{p.name}>" if p.required else f"[{p.name}]" for p in cmd.parameters)
                    syntax = f"/{attr.name} {cmd.name}" + (f" {params}" if params else "")
                    commands_list.append((syntax, cmd.description or "No description provided"))
        return commands_list

    def get_help_embed(self) -> discord.Embed:
        """Generates a dedicated help embed for this service."""
        embed = discord.Embed(
            title=f"{self.name.upper()} Service Help",
            description=f"Available slash commands for the `/{self.name}` service:",
            color=discord.Color.blurple(),
        )
        commands_list = self.get_help_commands()
        if commands_list:
            lines = [f"• `{syntax}` - {desc}" for syntax, desc in commands_list]
            embed.add_field(
                name="Commands",
                value="\n".join(lines),
                inline=False,
            )
        else:
            embed.description = "No commands registered for this service."
        embed.set_footer(text=f"Service: {self.name} | Type /{self.name} to view commands")
        return embed

    async def on_service_load(self) -> None:
        """Optional hook executed when the service is registered with the bot."""
        pass

    async def on_service_unload(self) -> None:
        """Optional hook executed when the service is unloaded."""
        pass

    async def cog_load(self) -> None:
        """Called by discord.py when the cog is loaded."""
        await self.on_service_load()

    async def cog_unload(self) -> None:
        """Called by discord.py when the cog is unloaded."""
        await self.on_service_unload()
