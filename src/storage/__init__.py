"""This modules implement access to global variables"""

from .dynamic_config_storage import (
    DYNAMIC_CONFIG_FILENAME,
    DYNAMIC_CONFIG_NOT_DEFINED,
)

from .storage import storage, reset_global_vars

__all__ = [
    "DYNAMIC_CONFIG_FILENAME",
    "DYNAMIC_CONFIG_NOT_DEFINED",
    "reset_global_vars",
    "storage",
]
