# -*- coding: utf-8 -*-
from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any, Final

from src.project import project_path_storage


MUTMUT_CONFIG_NOT_DEFINED = "Mutmut Config Not Defined"


def reset_global_vars() -> None:
    user_dynamic_config_storage.clear_mutmut_config_cache()
    project_path_storage.set_project_path()  # TODO: change to clear or reset


class UserDynamicConfigStorage:
    def __init__(self) -> None:
        self._cached_mutmut_config: Any = MUTMUT_CONFIG_NOT_DEFINED
        self._project_path_storage = project_path_storage

    def clear_mutmut_config_cache(self) -> None:
        self._cached_mutmut_config = MUTMUT_CONFIG_NOT_DEFINED

    def get_mutmut_config(self) -> Any:
        mutmut_config = self._get_mutmut_config()
        # print(f"{mutmut_config=}")
        return mutmut_config

    def _get_mutmut_config(self) -> Any:

        # mutmut_config es la configuracion en forma de archivo python que define el usuario
        if self._cached_mutmut_config != MUTMUT_CONFIG_NOT_DEFINED:
            return self._cached_mutmut_config

        current_project_path = self._project_path_storage.get_current_project_path()
        _cached_mutmut_config = self._import_mutmut_config(current_project_path)
        return _cached_mutmut_config

    def _import_mutmut_config(self, current_project_path: Path) -> Any:
        current_project_path_as_str = str(current_project_path)
        original_path = sys.path[:]
        if current_project_path_as_str not in sys.path:
            sys.path.insert(0, current_project_path_as_str)

        needs_reload = "mutmut_config" in sys.modules

        mutmut_config: Any = None

        try:
            import mutmut_config  # type: ignore [import-not-found, no-redef]
        except ImportError:
            pass

        if mutmut_config and needs_reload:
            try:
                importlib.reload(mutmut_config)
            except ImportError:
                mutmut_config = None

        sys.path = original_path
        return mutmut_config


# global variable
user_dynamic_config_storage: Final = UserDynamicConfigStorage()
