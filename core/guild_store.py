import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("bot.guild_store")


class GuildStore:
    """Persistent storage for per-guild dynamic configurations.

    JSON Structure:
    {
        "<guild_id>": {
            "<service_name>": {
                "key": "value"
            }
        }
    }
    """

    def __init__(self, file_path: str = "data/guild_settings.json") -> None:
        self.file_path = Path(file_path)
        self._data: Dict[str, Dict[str, Dict[str, Any]]] = {}
        self._lock = asyncio.Lock()
        self._load()

    def _load(self) -> None:
        """Loads saved configurations from disk if the file exists."""
        if self.file_path.exists():
            try:
                with open(self.file_path, "r", encoding="utf-8") as f:
                    self._data = json.load(f)
                logger.info("Successfully loaded guild settings from %s", self.file_path)
            except Exception as e:
                logger.error("Failed to load guild settings from %s: %s", self.file_path, e)
                self._data = {}
        else:
            self.file_path.parent.mkdir(parents=True, exist_ok=True)
            self._data = {}

    async def save(self) -> None:
        """Atomically saves settings to disk."""
        async with self._lock:
            try:
                self.file_path.parent.mkdir(parents=True, exist_ok=True)
                temp_file = self.file_path.with_suffix(".tmp")
                with open(temp_file, "w", encoding="utf-8") as f:
                    json.dump(self._data, f, indent=2, ensure_ascii=False)
                temp_file.replace(self.file_path)
            except Exception as e:
                logger.error("Failed to save guild settings to %s: %s", self.file_path, e)

    def get(self, guild_id: int, service: str, key: str, default: Any = None) -> Any:
        """Gets a configuration value for a specific guild and service."""
        gid = str(guild_id)
        return self._data.get(gid, {}).get(service, {}).get(key, default)

    def get_service_settings(self, guild_id: int, service: str) -> Dict[str, Any]:
        """Returns all stored settings for a service on a given guild."""
        gid = str(guild_id)
        return dict(self._data.get(gid, {}).get(service, {}))

    async def set(self, guild_id: int, service: str, key: str, value: Any) -> None:
        """Sets and persists a configuration value for a guild and service."""
        gid = str(guild_id)
        if gid not in self._data:
            self._data[gid] = {}
        if service not in self._data[gid]:
            self._data[gid][service] = {}

        self._data[gid][service][key] = value
        await self.save()

    async def remove(self, guild_id: int, service: str, key: str) -> bool:
        """Removes a specific configuration key for a guild."""
        gid = str(guild_id)
        if gid in self._data and service in self._data[gid] and key in self._data[gid][service]:
            del self._data[gid][service][key]
            await self.save()
            return True
        return False
