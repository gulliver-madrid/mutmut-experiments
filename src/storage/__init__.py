"""This modules implement access to global variables"""

from .project import ProjectPath

from .dynamic_config_storage import (
    DYNAMIC_CONFIG_FILENAME,
    DYNAMIC_CONFIG_NOT_DEFINED,
)

from .storage import storage, reset_global_vars

__all__ = [
    "ProjectPath",
    "DYNAMIC_CONFIG_FILENAME",
    "DYNAMIC_CONFIG_NOT_DEFINED",
    "reset_global_vars",
    "storage",
]
