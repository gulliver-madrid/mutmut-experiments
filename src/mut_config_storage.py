# -*- coding: utf-8 -*-
from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any, Final

from src.project import project_path_storage


MUTMUT_CONFIG_NOT_DEFINED = "Mutmut Config Not Defined"

DYNAMIC_CONFIG_NAME: Final = "mutmut_config"
DYNAMIC_CONFIG_FILENAME: Final = DYNAMIC_CONFIG_NAME + ".py"


def reset_global_vars() -> None:
    user_dynamic_config_storage.clear_dynamic_config_cache()
    project_path_storage.set_project_path()  # TODO: change to clear or reset


class UserDynamicConfigStorage:
    """Dynamic configuration is the configuration in the form of a Python file that is defined by the user."""

    def __init__(self) -> None:
        self._cached_dynamic_config: Any = MUTMUT_CONFIG_NOT_DEFINED
        self._project_path_storage = project_path_storage

    def clear_dynamic_config_cache(self) -> None:
        self._cached_dynamic_config = MUTMUT_CONFIG_NOT_DEFINED

    def get_dynamic_config(self) -> Any:
        dynamic_config = self._get_dynamic_config()
        return dynamic_config

    def _get_dynamic_config(self) -> Any:
        if self._cached_dynamic_config != MUTMUT_CONFIG_NOT_DEFINED:
            return self._cached_dynamic_config

        current_project_path = self._project_path_storage.get_current_project_path()
        _cached_dynamic_config = self._import_dynamic_config(current_project_path)
        return _cached_dynamic_config

    def _import_dynamic_config(self, current_project_path: Path) -> Any:
        current_project_path_as_str = str(current_project_path)
        original_path = sys.path[:]
        if current_project_path_as_str not in sys.path:
            sys.path.insert(0, current_project_path_as_str)

        needs_reload = DYNAMIC_CONFIG_NAME in sys.modules

        dynamic_config: Any = None

        try:
            dynamic_config = importlib.import_module(DYNAMIC_CONFIG_NAME)
        except ImportError:
            pass

        if dynamic_config and needs_reload:
            try:
                importlib.reload(dynamic_config)
            except ImportError:
                dynamic_config = None

        sys.path = original_path
        return dynamic_config


# global variable
user_dynamic_config_storage: Final = UserDynamicConfigStorage()
