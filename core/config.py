"""Typed configuration models and dynamic SQLite schema generation."""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass
import json
import logging
from pathlib import Path
from typing import Any, ClassVar, Dict, List, Optional, Tuple, Type, TypeVar, Union, get_args, get_origin, get_type_hints

from core.exceptions import ConfigValidationError

logger = logging.getLogger("bot.core.config")

TConfig = TypeVar("TConfig", bound="BaseConfigModel")
TGuildConfig = TypeVar("TGuildConfig", bound="BaseGuildConfig")


def _unwrap_optional(tp: Any) -> Any:
    """Unwraps Optional[T] / Union[T, None] into T."""
    origin = get_origin(tp)
    if origin is Union:
        args = [a for a in get_args(tp) if a is not type(None)]
        if len(args) == 1:
            return args[0]
    return tp


def _python_type_to_sqlite(tp: Any) -> str:
    """Maps a Python type annotation to its corresponding SQLite column affinity."""
    base_type = _unwrap_optional(tp)
    if base_type in (int, bool):
        return "INTEGER"
    if base_type is float:
        return "REAL"
    return "TEXT"


class BaseConfigModel:
    """Base class for typed JSON configuration models (config/<name>.json)."""

    @classmethod
    def from_dict(cls: Type[TConfig], data: Dict[str, Any], source_path: Optional[Union[str, Path]] = None) -> TConfig:
        """Validates that all dataclass fields exist in `data` and instantiates the model."""
        if not dataclasses.is_dataclass(cls):
            raise TypeError(f"{cls.__name__} must be decorated with @dataclass")

        field_names = {f.name for f in dataclasses.fields(cls)}
        missing = field_names - set(data.keys())
        if missing:
            loc = f" in {source_path}" if source_path else ""
            msg = f"Configuration error for {cls.__name__}: missing required keys{loc}: {sorted(missing)}"
            logger.critical(msg)
            raise ConfigValidationError(msg)

        filtered = {k: data[k] for k in field_names}
        return cls(**filtered)

    @classmethod
    def from_json_file(cls: Type[TConfig], path: Union[str, Path]) -> TConfig:
        """Loads, parses, and validates a JSON configuration file into a typed model."""
        file_path = Path(path)
        if not file_path.exists():
            msg = f"Configuration file not found: {file_path} does not exist."
            logger.critical(msg)
            raise ConfigValidationError(msg)

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                raw_data = json.load(f)
        except Exception as e:
            msg = f"Failed to read or parse configuration file {file_path}: {e}"
            logger.critical(msg)
            raise ConfigValidationError(msg)

        if not isinstance(raw_data, dict):
            msg = f"Invalid configuration format in {file_path}: expected a JSON object."
            logger.critical(msg)
            raise ConfigValidationError(msg)

        instance = cls.from_dict(raw_data, source_path=file_path)
        logger.info("Loaded configuration model '%s' from %s", cls.__name__, file_path)
        return instance

    def to_dict(self) -> Dict[str, Any]:
        """Serializes the configuration model back to a dictionary."""
        return dataclasses.asdict(self)

    def save_to_file(self, path: Union[str, Path]) -> None:
        """Writes the configuration model to disk as formatted JSON."""
        file_path = Path(path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)
        logger.info("Saved configuration model '%s' to %s", self.__class__.__name__, file_path)

    def get(self, key: str, default: Any = None) -> Any:
        """Dictionary-compatible getter for configuration attributes."""
        return getattr(self, key, default)

    def __getitem__(self, key: str) -> Any:
        """Dictionary-compatible bracket access for configuration attributes."""
        if hasattr(self, key):
            return getattr(self, key)
        raise KeyError(key)

    def __contains__(self, key: str) -> bool:
        return hasattr(self, key)

    def keys(self):
        return [f.name for f in dataclasses.fields(self)]

    def get_numeric_bounds(
        self, key: str, default_min: Optional[Any] = None, default_max: Optional[Any] = None
    ) -> Tuple[Any, Any]:
        """Retrieves static (min, max) bounds defined on the configuration model."""
        min_val = getattr(self, f"{key}_min", getattr(self, f"min_{key}", default_min))
        max_val = getattr(self, f"{key}_max", getattr(self, f"max_{key}", default_max))
        return min_val, max_val


@dataclass
class BaseGuildConfig:
    """Base class for per-guild SQLite configuration models.

    Subclasses define `table_name` and typed fields representing columns in SQLite.
    SQLite `CREATE TABLE` statements and queries are generated automatically by inspecting
    the dataclass fields and type annotations.
    """

    table_name: ClassVar[str] = "base_config"
    guild_id: int

    @classmethod
    def get_column_types(cls) -> Dict[str, str]:
        """Inspects dataclass fields and returns a mapping of column_name -> SQLite type."""
        hints = get_type_hints(cls)
        columns: Dict[str, str] = {}
        for f in dataclasses.fields(cls):
            field_type = hints.get(f.name, f.type)
            columns[f.name] = _python_type_to_sqlite(field_type)
        return columns

    @classmethod
    def get_create_table_sql(cls) -> str:
        """Generates the SQLite CREATE TABLE statement dynamically from the class fields."""
        col_defs: List[str] = []
        for col_name, sql_type in cls.get_column_types().items():
            if col_name == "guild_id":
                col_defs.append("guild_id INTEGER PRIMARY KEY")
            else:
                col_defs.append(f"{col_name} {sql_type}")
        cols_joined = ",\n            ".join(col_defs)
        return f"CREATE TABLE IF NOT EXISTS {cls.table_name} (\n            {cols_joined}\n        )"

    @classmethod
    def from_row(cls: Type[TGuildConfig], guild_id: int, row: Optional[Any] = None) -> TGuildConfig:
        """Instantiates the guild config model from a sqlite3.Row or dictionary."""
        if row is None:
            return cls(guild_id=guild_id)
        row_dict = dict(row)
        kwargs: Dict[str, Any] = {"guild_id": guild_id}
        for f in dataclasses.fields(cls):
            if f.name != "guild_id" and f.name in row_dict:
                kwargs[f.name] = row_dict[f.name]
        return cls(**kwargs)

    def to_dict(self, exclude_none: bool = True) -> Dict[str, Any]:
        """Returns custom guild settings as a dictionary."""
        result: Dict[str, Any] = {}
        for f in dataclasses.fields(self):
            if f.name == "guild_id":
                continue
            val = getattr(self, f.name)
            if not exclude_none or val is not None:
                result[f.name] = val
        return result


@dataclass
class BotConfig(BaseConfigModel):
    """Typed model representing `config/bot.json`."""

    prefix: str
    description: str
    sync_commands_on_startup: bool
    status_message: str
    ffmpeg_path: str
    db_path: str
    db_timeout: float
    services_dir: str
    config_dir: str
    log_dir: str
    log_file: str
    default_log_level: str
    log_format: str
    log_date_format: str
    stream_before_options: str
    stream_options: str
    local_file_options: str
    auto_disconnect_timeout: int
    auto_disconnect_timeout_min: int
    auto_disconnect_timeout_max: int
    voice_connect_timeout: float
    max_queue_display: int
    max_autocomplete_choices: int
    timeout_choices: List[List[Any]]


@dataclass
class BotGuildConfig(BaseGuildConfig):
    """Per-guild SQLite configuration model for the core bot (`bot_config` table)."""

    table_name: ClassVar[str] = "bot_config"

    guild_id: int
    auto_disconnect_timeout: Optional[int] = None
