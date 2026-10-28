"""Custom exceptions for the modular bot architecture."""
from __future__ import annotations


class ConfigValidationError(Exception):
    """Raised when configuration file is missing or lacks required keys."""
    pass
