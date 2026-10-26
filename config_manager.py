"""Backward-compatible proxy for core.config.
"""

from core.config import (
    CONFIG_FILE_NAME,
    get_config_path,
    load_config,
    save_config,
)

__all__ = [
    "CONFIG_FILE_NAME",
    "get_config_path",
    "load_config",
    "save_config",
]
