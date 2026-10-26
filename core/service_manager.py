from __future__ import annotations
import importlib
import inspect
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional, Type

from core.service_base import BaseService

if TYPE_CHECKING:
    from core.bot import ModularBot

logger = logging.getLogger("bot.service_manager")


class ServiceManager:
    """Manages discovery, loading, unloading, and configuration of modular bot services."""

    def __init__(self, bot: ModularBot, services_dir: str = "services", config_dir: str = "config") -> None:
        self.bot = bot
        self.services_dir = Path(services_dir)
        self.config_dir = Path(config_dir)
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.services: Dict[str, BaseService] = {}

    def load_service_config(self, service_name: str) -> Dict:
        """Loads the dedicated configuration file for a service from config/<service_name>.json."""
        config_path = self.config_dir / f"{service_name}.json"
        if config_path.exists():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error("Failed to read configuration for '%s' at %s: %s", service_name, config_path, e)
                return {}

        # If config file does not exist, load defaults from the service defaults module
        try:
            defaults_mod = importlib.import_module(f"{self.services_dir.name}.{service_name}.defaults")
            if hasattr(defaults_mod, "get_default_config"):
                defaults = defaults_mod.get_default_config()
                self.save_service_config(service_name, defaults)
                return defaults
        except Exception:
            pass

        return {}

    def save_service_config(self, service_name: str, config: Dict) -> None:
        """Saves service configuration to disk."""
        config_path = self.config_dir / f"{service_name}.json"
        try:
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
                # Checks if service.py or __init__.py exists in the subdirectory
                if (item / "service.py").exists() or (item / "__init__.py").exists():
                    discovered.append(item.name)
        return sorted(discovered)

    async def load_service(self, service_name: str) -> bool:
        """Loads and instantiates a specific service."""
        if service_name in self.services:
            logger.warning("Service '%s' is already loaded.", service_name)
            return True

        # Load service configuration
        config = self.load_service_config(service_name)
        if not config.get("enabled", True):
            logger.info("Service '%s' is disabled in its configuration.", service_name)
            return False

        module_path = f"{self.services_dir.name}.{service_name}.service"
        try:
            # Import or reload module
            module = importlib.import_module(module_path)
            importlib.reload(module)

            # Find class that inherits from BaseService
            service_class: Optional[Type[BaseService]] = None
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
                logger.error("No class inheriting from BaseService was found in %s", module_path)
                return False

            instance = service_class(self.bot, config=config)
            await self.bot.add_cog(instance)
            self.services[service_name] = instance
            logger.info("Service '%s' loaded successfully!", service_name)
            return True

        except Exception as e:
            logger.exception("Failed to load service '%s': %s", service_name, e)
            return False

    async def unload_service(self, service_name: str) -> bool:
        """Unloads a currently loaded service."""
        if service_name not in self.services:
            logger.warning("Service '%s' is not loaded.", service_name)
            return False

        instance = self.services[service_name]
        try:
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

    def get_service(self, name: str) -> Optional[BaseService]:
        """Returns a service instance by name."""
        return self.services.get(name)
