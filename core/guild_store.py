from __future__ import annotations
import asyncio
import logging
from pathlib import Path
import sqlite3
from typing import Any, Dict, Optional

from core.defaults import DEFAULT_DB_PATH

logger = logging.getLogger("bot.guild_store")

TABLE_SCHEMAS: Dict[str, str] = {
    "bot_config": """
        CREATE TABLE IF NOT EXISTS bot_config (
            guild_id INTEGER PRIMARY KEY,
            auto_disconnect_timeout INTEGER
        )
    """,
    "tts_config": """
        CREATE TABLE IF NOT EXISTS tts_config (
            guild_id INTEGER PRIMARY KEY,
            voice TEXT,
            voice_speed REAL,
            volume INTEGER,
            max_text_length INTEGER,
            intro_sound TEXT,
            intro_delay REAL,
            bound_channel_id INTEGER
        )
    """,
    "yt_config": """
        CREATE TABLE IF NOT EXISTS yt_config (
            guild_id INTEGER PRIMARY KEY,
            volume INTEGER
        )
    """,
}

GLOBAL_SETTING_KEYS = {
    "filter_urls",
    "ffmpeg_path",
    "sounds_dir",
    "enabled",
    "read_bot_messages",
    "prefix",
    "description",
    "sync_commands",
    "status_message",
}


class GuildStore:
    """Persistent SQLite storage for per-guild dynamic configurations.

    Each service has a dedicated SQLite table:
    - bot_config (core bot settings)
    - tts_config (text-to-speech settings)
    - yt_config (YouTube music playback settings)
    """

    def __init__(self, db_path: str = DEFAULT_DB_PATH) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()

        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")

        self._init_tables()

    def _table_name(self, service: str) -> str:
        """Normalizes a service name to its dedicated SQLite table name."""
        clean = service.lower().strip()
        if clean.endswith("_config"):
            return clean
        return f"{clean}_config"

    def _init_tables(self) -> None:
        """Initializes primary tables for all known services."""
        cursor = self._conn.cursor()
        for schema_sql in TABLE_SCHEMAS.values():
            cursor.execute(schema_sql)
        self._conn.commit()

    def _ensure_table(self, cursor: sqlite3.Cursor, table: str) -> None:
        """Ensures that a service table exists, creating it dynamically if necessary."""
        if table in TABLE_SCHEMAS:
            cursor.execute(TABLE_SCHEMAS[table])
        else:
            cursor.execute(f"CREATE TABLE IF NOT EXISTS {table} (guild_id INTEGER PRIMARY KEY)")

    def _ensure_column(
        self, cursor: sqlite3.Cursor, table: str, column: str, value: Any
    ) -> None:
        """Ensures that a column exists in the table, adding it dynamically if needed."""
        cursor.execute(f"PRAGMA table_info({table})")
        existing_cols = [row["name"] for row in cursor.fetchall()]
        if column not in existing_cols:
            col_type = "TEXT"
            if isinstance(value, bool) or isinstance(value, int):
                col_type = "INTEGER"
            elif isinstance(value, float):
                col_type = "REAL"
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")

    def get(self, guild_id: int, service: str, key: str, default: Any = None) -> Any:
        """Retrieves a configuration value for a specific guild and service."""
        table = self._table_name(service)
        try:
            cursor = self._conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
            if not cursor.fetchone():
                return default

            cursor.execute(f"PRAGMA table_info({table})")
            columns = [row["name"] for row in cursor.fetchall()]
            if key not in columns:
                return default

            cursor.execute(f"SELECT {key} FROM {table} WHERE guild_id = ?", (int(guild_id),))
            row = cursor.fetchone()
            if row and row[key] is not None:
                return row[key]
            return default
        except Exception as e:
            logger.error("Error reading %s.%s for guild %s: %s", table, key, guild_id, e)
            return default

    def get_service_settings(self, guild_id: int, service: str) -> Dict[str, Any]:
        """Returns all stored configuration overrides for a service on a given guild."""
        table = self._table_name(service)
        try:
            cursor = self._conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
            if not cursor.fetchone():
                return {}

            cursor.execute(f"SELECT * FROM {table} WHERE guild_id = ?", (int(guild_id),))
            row = cursor.fetchone()
            if not row:
                return {}

            settings: Dict[str, Any] = {}
            for col in row.keys():
                if col != "guild_id" and row[col] is not None:
                    settings[col] = row[col]
            return settings
        except Exception as e:
            logger.error("Error fetching all settings for %s in guild %s: %s", table, guild_id, e)
            return {}

    async def set(self, guild_id: int, service: str, key: str, value: Any) -> None:
        """Sets and persists a configuration value for a guild and service in its SQLite table."""
        if key in GLOBAL_SETTING_KEYS:
            logger.debug("Skipping global setting '%s' in guild store for guild %s", key, guild_id)
            return

        async with self._lock:
            table = self._table_name(service)
            try:
                cursor = self._conn.cursor()
                self._ensure_table(cursor, table)
                self._ensure_column(cursor, table, key, value)

                db_val = int(value) if isinstance(value, bool) else value
                cursor.execute(
                    f"""
                    INSERT INTO {table} (guild_id, {key})
                    VALUES (?, ?)
                    ON CONFLICT(guild_id) DO UPDATE SET {key} = excluded.{key}
                    """,
                    (int(guild_id), db_val),
                )
                self._conn.commit()
            except Exception as e:
                logger.error("Failed to set %s.%s for guild %s: %s", table, key, guild_id, e)

    async def remove(self, guild_id: int, service: str, key: str) -> bool:
        """Unsets a specific configuration key (sets to NULL) for a guild."""
        async with self._lock:
            table = self._table_name(service)
            try:
                cursor = self._conn.cursor()
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
                if not cursor.fetchone():
                    return False

                cursor.execute(f"PRAGMA table_info({table})")
                columns = [row["name"] for row in cursor.fetchall()]
                if key not in columns:
                    return False

                cursor.execute(f"UPDATE {table} SET {key} = NULL WHERE guild_id = ?", (int(guild_id),))
                self._conn.commit()
                return cursor.rowcount > 0
            except Exception as e:
                logger.error("Failed to remove %s.%s for guild %s: %s", table, key, guild_id, e)
                return False

    async def save(self) -> None:
        """Commits active transactions (retained for backward compatibility)."""
        async with self._lock:
            self._conn.commit()

    def close(self) -> None:
        """Closes the underlying SQLite database connection."""
        try:
            self._conn.close()
        except Exception:
            pass
