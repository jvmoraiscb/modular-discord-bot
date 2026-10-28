"""Dynamic model-driven SQLite storage for per-guild configurations."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
import sqlite3
from typing import Any, Dict, Optional, Type, TypeVar

from core.config import BaseGuildConfig, BotGuildConfig

logger = logging.getLogger("bot.guild_store")

TGuildModel = TypeVar("TGuildModel", bound=BaseGuildConfig)


class GuildStore:
    """Persistent SQLite storage driven by BaseGuildConfig model classes."""

    def __init__(self, db_path: str, timeout: float = 30.0) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.timeout = float(timeout)
        self._lock = asyncio.Lock()
        self._models: Dict[str, Type[BaseGuildConfig]] = {}

        # Always register the core bot guild configuration model
        self.register_model("bot", BotGuildConfig)

    def _get_connection(self) -> sqlite3.Connection:
        """Returns a connection to the SQLite database with WAL journal mode enabled."""
        conn = sqlite3.connect(str(self.db_path), timeout=self.timeout)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        return conn

    def register_model(self, service_name: str, model_cls: Type[BaseGuildConfig]) -> None:
        """Registers a service's guild config model and automatically creates/migrates its SQLite table."""
        self._models[service_name] = model_cls
        create_sql = model_cls.get_create_table_sql()
        expected_columns = model_cls.get_column_types()

        with self._get_connection() as conn:
            with conn:
                conn.execute(create_sql)
                # Ensure any newly added fields on the dataclass exist as columns in SQLite
                cursor = conn.execute(f"PRAGMA table_info({model_cls.table_name})")
                existing_cols = {row["name"] for row in cursor.fetchall()}
                for col_name, col_type in expected_columns.items():
                    if col_name not in existing_cols:
                        conn.execute(
                            f"ALTER TABLE {model_cls.table_name} ADD COLUMN {col_name} {col_type}"
                        )
                        logger.info(
                            "Added new column '%s' (%s) to table '%s'",
                            col_name,
                            col_type,
                            model_cls.table_name,
                        )

        logger.info(
            "Registered guild config model '%s' -> table '%s' at %s",
            model_cls.__name__,
            model_cls.table_name,
            self.db_path,
        )

    def get_model_class(self, service_name: str) -> Optional[Type[BaseGuildConfig]]:
        """Returns the registered BaseGuildConfig class for a service."""
        return self._models.get(service_name)

    def get_guild_config(self, guild_id: int, service_name: str) -> Optional[BaseGuildConfig]:
        """Synchronously loads the full typed guild configuration object for a service."""
        model_cls = self._models.get(service_name)
        if not model_cls:
            return None

        query = f"SELECT * FROM {model_cls.table_name} WHERE guild_id = ?"
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(query, (guild_id,))
                row = cursor.fetchone()
                return model_cls.from_row(guild_id, row)
        except Exception as e:
            logger.error("Failed to load guild config [%s] for guild %s: %s", service_name, guild_id, e)
            return model_cls(guild_id=guild_id)

    def get(self, guild_id: int, service_name: str, key: str) -> Optional[Any]:
        """Synchronously reads a single guild configuration setting via the registered model."""
        guild_cfg = self.get_guild_config(guild_id, service_name)
        if guild_cfg is None or not hasattr(guild_cfg, key):
            return None
        return getattr(guild_cfg, key)

    async def set(self, guild_id: int, service_name: str, key: str, value: Any) -> None:
        """Asynchronously writes a guild configuration setting validated against the service model."""
        model_cls = self._models.get(service_name)
        if not model_cls:
            logger.warning("Attempted to set setting for unregistered service: %s", service_name)
            return

        if key not in model_cls.get_column_types() or key == "guild_id":
            logger.warning("Invalid column '%s' for model '%s'", key, model_cls.__name__)
            return

        async with self._lock:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._set_sync, guild_id, model_cls.table_name, key, value)

    def _set_sync(self, guild_id: int, table_name: str, key: str, value: Any) -> None:
        """Synchronous write logic executed in a worker thread."""
        query = f"""
            INSERT INTO {table_name} (guild_id, {key})
            VALUES (?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET {key} = excluded.{key}
        """
        try:
            with self._get_connection() as conn:
                with conn:
                    conn.execute(query, (guild_id, value))
        except Exception as e:
            logger.error("Failed to write %s to %s for guild %s: %s", key, table_name, guild_id, e)

    async def get_all_guild_settings(self, guild_id: int, service_name: str) -> Dict[str, Any]:
        """Returns all custom saved settings for a specific guild and service as a dictionary."""
        async with self._lock:
            loop = asyncio.get_event_loop()
            cfg = await loop.run_in_executor(None, self.get_guild_config, guild_id, service_name)
            return cfg.to_dict(exclude_none=True) if cfg else {}
