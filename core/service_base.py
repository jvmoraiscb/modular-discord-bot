"""Base class for all pluggable bot services."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, ClassVar, Dict, Generic, Optional, TYPE_CHECKING, Type, TypeVar, Union

from discord.ext import commands

from core.config import BaseConfigModel, BaseGuildConfig
from core.exceptions import ConfigValidationError

if TYPE_CHECKING:
    from core.bot import ModularBot

TServiceConfig = TypeVar("TServiceConfig", bound=BaseConfigModel)
TGuildConfig = TypeVar("TGuildConfig", bound=BaseGuildConfig)


class BaseService(commands.Cog, Generic[TServiceConfig, TGuildConfig]):
    """Base class for all pluggable bot services.

    Each service defines:
    - `config_class`: Typed `BaseConfigModel` subclass representing `config/<service_name>.json`.
    - `guild_config_class`: Typed `BaseGuildConfig` subclass representing its SQLite table.
    """

    name: str = "base_service"
    config_class: ClassVar[Optional[Type[BaseConfigModel]]] = None
    guild_config_class: ClassVar[Optional[Type[BaseGuildConfig]]] = None

    def __init__(
        self,
        bot: ModularBot,
        config: Optional[Union[TServiceConfig, Dict[str, Any]]] = None,
    ) -> None:
        self.bot = bot
        self.logger = logging.getLogger(f"bot.service.{self.name}")
        self.config: TServiceConfig = self._initialize_config(config)

        # Register the service's per-guild SQLite model automatically
        if self.guild_config_class is not None and hasattr(self.bot, "guild_persistence"):
            self.bot.guild_persistence.register_model(self.name, self.guild_config_class)

    def _initialize_config(
        self, raw_config: Optional[Union[TServiceConfig, Dict[str, Any]]]
    ) -> TServiceConfig:
        """Instantiates and validates the typed configuration model for this service."""
        if self.config_class is None:
            raise ConfigValidationError(
                f"Service '{self.name}' must define a 'config_class' inheriting from BaseConfigModel."
            )

        if isinstance(raw_config, self.config_class):
            return raw_config  # type: ignore[return-value]

        if isinstance(raw_config, dict):
            return self.config_class.from_dict(raw_config, source_path=self.get_config_path())  # type: ignore[return-value]

        return self.config_class.from_json_file(self.get_config_path())  # type: ignore[return-value]

    def get_config_path(self) -> Path:
        """Returns the configuration file path for this service."""
        config_dir = self.bot.bot_config.config_dir
        return Path(config_dir) / f"{self.name}.json"

    def save_config(self) -> None:
        """Saves the typed service configuration model to disk."""
        path = self.get_config_path()
        try:
            self.config.save_to_file(path)
            self.logger.info("Configuration for service '%s' successfully saved.", self.name)
        except Exception as e:
            self.logger.error("Failed to save configuration for '%s': %s", self.name, e)

    def get_guild_config(self, guild_id: int) -> Optional[TGuildConfig]:
        """Returns the full typed per-guild configuration model from SQLite."""
        if hasattr(self.bot, "guild_persistence"):
            return self.bot.guild_persistence.get_guild_config(guild_id, self.name)  # type: ignore[return-value]
        return None

    def get_guild_setting(self, guild_id: Optional[int], key: str, default: Any = None) -> Any:
        """Retrieves a configuration value for the specified guild.

        If the guild has a saved custom override in its SQLite model, that value is returned.
        Otherwise, it falls back to the value from the service's typed config model.
        """
        if guild_id is not None and hasattr(self.bot, "guild_persistence"):
            custom_val = self.bot.guild_persistence.get(guild_id, self.name, key)
            if custom_val is not None:
                return custom_val

        return self.config.get(key, default)

    async def set_guild_setting(self, guild_id: int, key: str, value: Any) -> None:
        """Saves a custom configuration value for a guild via its SQLite model."""
        if hasattr(self.bot, "guild_persistence"):
            await self.bot.guild_persistence.set(guild_id, self.name, key, value)
            self.logger.debug("Updated guild %s setting '%s' to %r", guild_id, key, value)

    def get_numeric_bounds(
        self, key: str, default_min: Optional[Any] = None, default_max: Optional[Any] = None
    ) -> tuple[Any, Any]:
        """Retrieves static (min, max) limits defined directly in the service configuration model."""
        return self.config.get_numeric_bounds(key, default_min=default_min, default_max=default_max)

    async def on_service_load(self) -> None:
        """Hook called immediately after service is loaded."""
        self.logger.debug("Service '%s' load hook executed.", self.name)

    async def on_service_unload(self) -> None:
        """Hook called immediately before service is unloaded."""
        self.logger.debug("Service '%s' unload hook executed.", self.name)
