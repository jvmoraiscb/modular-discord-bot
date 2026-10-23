from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Optional

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
        self.config = config or {}
        self.logger = logging.getLogger(f"bot.service.{self.name}")

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

    def get_effective_config(self, guild_id: Optional[int]) -> Dict[str, Any]:
        """Returns the complete effective configuration for a guild (defaults merged with overrides)."""
        effective = dict(self.config)
        if guild_id is not None and hasattr(self.bot, "guild_store"):
            guild_overrides = self.bot.guild_store.get_service_settings(guild_id, self.name)
            effective.update(guild_overrides)
        return effective

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
