# -*- coding: utf-8 -*-
from __future__ import annotations

import os
from pathlib import Path
from typing import Final, NewType


ProjectPath = NewType("ProjectPath", Path)


class ProjectPathStorage:
    def __init__(self) -> None:
        self._cached_project_path: ProjectPath | None = None

    def get_current_project_path(self) -> Path:
        """
        Returns the path of the current project, where files such as .mutmut_cache, .coverage, or the dynamic config, are located.
        """
        current_project_path = self.get_project_path() or Path(os.getcwd())
        assert current_project_path.exists()
        return current_project_path

    def get_project_path(self) -> ProjectPath | None:
        """It could to be None. In that case, calling code probably should use os.getcwd()."""
        return self._cached_project_path

    def reset(self) -> None:
        self._cached_project_path = None

    def set_project_path(self, project: str | Path | None) -> None:
        if isinstance(project, str):
            project = Path(project)
        if project is None:
            self._cached_project_path = None
        else:
            project_path = ProjectPath(project.resolve())
            assert project_path.exists(), (f"{project=}", f"{project_path=}")
            self._cached_project_path = project_path


class TempDirectoryStorage:
    tmpdirname: str | None = None


# global variables
project_path_storage: Final = ProjectPathStorage()
temp_dir_storage: Final = TempDirectoryStorage()
