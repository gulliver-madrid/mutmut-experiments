# -*- coding: utf-8 -*-
from __future__ import annotations

import importlib
from pathlib import Path
import sys
from typing import Any

from mutmut.project import get_current_project_path


MUTMUT_CONFIG_NOT_DEFINED = 'Mutmut Config Not Defined'

# global variable
_cached_mutmut_config: Any = MUTMUT_CONFIG_NOT_DEFINED


def clear_mutmut_config_cache() -> None:
    global _cached_mutmut_config
    _cached_mutmut_config = MUTMUT_CONFIG_NOT_DEFINED


def get_mutmut_config() -> Any:
    global _cached_mutmut_config
    # mutmut_config es la configuracion en forma de archivo python que define el usuario
    if _cached_mutmut_config != MUTMUT_CONFIG_NOT_DEFINED:
        return _cached_mutmut_config

    current_project_path = get_current_project_path()
    _cached_mutmut_config = _import_mutmut_config(current_project_path)
    return _cached_mutmut_config

def _import_mutmut_config(current_project_path: Path) -> Any:
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
