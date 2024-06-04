"""This modules implement access to global variables"""

from .project import ProjectPath, project_path_storage, temp_dir_storage

from .dynamic_config_storage import (
    DYNAMIC_CONFIG_FILENAME,
    DYNAMIC_CONFIG_NOT_DEFINED,
    reset_global_vars,
    user_dynamic_config_storage,
)

__all__ = [
    "ProjectPath",
    "project_path_storage",
    "temp_dir_storage",
    "DYNAMIC_CONFIG_FILENAME",
    "DYNAMIC_CONFIG_NOT_DEFINED",
    "reset_global_vars",
    "user_dynamic_config_storage",
]
