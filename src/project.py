# -*- coding: utf-8 -*-
from __future__ import annotations

import os
from pathlib import Path
from typing import NewType


ProjectPath = NewType("ProjectPath", Path)

# global variable
_cached_project_path: ProjectPath | None = None


def get_current_project_path() -> Path:
    """
    Returns the path of the current project, where files such as .mutmut_cache, mutmut_config.py,
    .coverage, etc, are located.
    """
    current_project_path = get_project_path() or Path(os.getcwd())
    assert current_project_path.exists()
    return current_project_path


def get_project_path() -> ProjectPath | None:
    """It could to be None. In that case, calling code probably should use os.getcwd()."""
    return _cached_project_path


def set_project_path(project: str | Path | None = None) -> None:
    global _cached_project_path
    if isinstance(project, str):
        project = Path(project)
    if project is None:
        _cached_project_path = None
    else:
        project_path = ProjectPath(project.resolve())
        assert project_path.exists(), (f"{project=}", f"{project_path=}")
        _cached_project_path = project_path
