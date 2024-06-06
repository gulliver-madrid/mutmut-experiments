# -*- coding: utf-8 -*-
from __future__ import annotations

import os
from pathlib import Path

from src.tools import configure_logger

logger = configure_logger(__name__)


class ProjectPathStorage:
    def __init__(self) -> None:
        self._cached_project_path: Path | None = None

    def get_current_project_path(self) -> Path:
        """
        Returns the path of the current project, where files such as .mutmut_cache, .coverage, or the dynamic config, are located.
        """
        if not self._cached_project_path:
            self._cached_project_path = Path(os.getcwd())

        assert self._cached_project_path.exists()
        return self._cached_project_path

    def reset(self) -> None:
        self._cached_project_path = None

    def set_project_path(self, project: str | Path | None) -> None:
        if isinstance(project, str):
            project = Path(project)
        if project is None:
            self._cached_project_path = None
        else:
            project = project.resolve()
            assert project.exists()
            self._cached_project_path = project


class TempDirectoryStorage:
    tmpdirname: str | None = None

    def reset(self) -> None:
        self.tmpdirname = None
