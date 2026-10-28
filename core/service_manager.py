"""Service manager for discovering and dynamically managing modular services."""
from __future__ import annotations

import importlib
import inspect
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING, Type

from core.config import BaseConfigModel
from core.exceptions import ConfigValidationError
from core.service_base import BaseService

if TYPE_CHECKING:
    from core.bot import ModularBot

logger = logging.getLogger("bot.service_manager")


class ServiceManager:
    """Manages discovery, loading, unloading, and configuration of modular bot services."""

    def __init__(self, bot: ModularBot, services_dir: str, config_dir: str) -> None:
        self.bot = bot
        self.services_dir = Path(services_dir)
        self.config_dir = Path(config_dir)
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.services: Dict[str, BaseService[Any, Any]] = {}

    def load_service_config(self, service_name: str) -> Dict[str, Any]:
        """Loads the raw JSON configuration dictionary for a service from config/<service_name>.json."""
        config_path = self.config_dir / f"{service_name}.json"
        if not config_path.exists():
            msg = f"Configuration file not found for service '{service_name}': {config_path} does not exist."
            logger.critical(msg)
            raise ConfigValidationError(msg)

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            msg = f"Failed to read or parse configuration for service '{service_name}' at {config_path}: {e}"
            logger.critical(msg)
            raise ConfigValidationError(msg)

    def save_service_config(self, service_name: str, config: BaseConfigModel | Dict[str, Any]) -> None:
        """Saves service configuration to disk."""
        config_path = self.config_dir / f"{service_name}.json"
        try:
            if isinstance(config, BaseConfigModel):
                config.save_to_file(config_path)
            else:
                with open(config_path, "w", encoding="utf-8") as f:
                    json.dump(config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error("Failed to save configuration for '%s' at %s: %s", service_name, config_path, e)

    def discover_services(self) -> List[str]:
        """Discovers valid service directories inside the services/ folder."""
        if not self.services_dir.exists():
            self.services_dir.mkdir(parents=True, exist_ok=True)
            return []

        discovered = []
        for item in self.services_dir.iterdir():
            if item.is_dir() and not item.name.startswith(("_", ".")):
                if (item / "service.py").exists() or (item / "__init__.py").exists():
                    discovered.append(item.name)
        return sorted(discovered)

    async def load_service(self, service_name: str) -> bool:
        """Loads and instantiates a specific service using its typed config and guild config models."""
        if service_name in self.services:
            logger.warning("Service '%s' is already loaded.", service_name)
            return True

        raw_config = self.load_service_config(service_name)
        if not raw_config.get("enabled", True):
            logger.info("Service '%s' is disabled in its configuration.", service_name)
            return False

        module_path = f"{self.services_dir.name}.{service_name}.service"
        try:
            module = importlib.import_module(module_path)
            importlib.reload(module)

            service_class: Optional[Type[BaseService[Any, Any]]] = None
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (
                    inspect.isclass(attr)
                    and issubclass(attr, BaseService)
                    and attr is not BaseService
                ):
                    service_class = attr
                    break

            if not service_class:
                msg = f"No class inheriting from BaseService was found in {module_path}"
                logger.critical(msg)
                raise ConfigValidationError(msg)

            instance = service_class(self.bot, config=raw_config)
            await self.bot.add_cog(instance)
            await instance.on_service_load()
            self.services[service_name] = instance
            logger.info("Service '%s' loaded successfully!", service_name)
            return True

        except ConfigValidationError:
            raise
        except Exception as e:
            logger.exception("Failed to load service '%s': %s", service_name, e)
            raise ConfigValidationError(f"Failed to load service '{service_name}': {e}") from e

    async def unload_service(self, service_name: str) -> bool:
        """Unloads a currently loaded service."""
        if service_name not in self.services:
            logger.warning("Service '%s' is not loaded.", service_name)
            return False

        instance = self.services[service_name]
        try:
            await instance.on_service_unload()
            await self.bot.remove_cog(instance.qualified_name)
            del self.services[service_name]
            logger.info("Service '%s' unloaded successfully.", service_name)
            return True
        except Exception as e:
            logger.exception("Failed to unload service '%s': %s", service_name, e)
            return False

    async def reload_service(self, service_name: str) -> bool:
        """Reloads a service."""
        if service_name in self.services:
            await self.unload_service(service_name)
        return await self.load_service(service_name)

    async def load_all(self) -> None:
        """Discovers and loads all available services."""
        services = self.discover_services()
        logger.info("Detected services: %s", services)
        for s in services:
            await self.load_service(s)

    def get_service(self, name: str) -> Optional[BaseService[Any, Any]]:
        """Returns a service instance by name."""
        return self.services.get(name)
