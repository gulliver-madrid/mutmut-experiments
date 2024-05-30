import os
from pathlib import Path
from typing import Any


class DirContext:
    def __init__(self, directory: Path | str) -> None:
        self._directory = directory
        self._original_directory: str | None = None

    def __enter__(self) -> "DirContext":
        self._original_directory = os.getcwd()
        os.chdir(self._directory)
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        assert self._original_directory
        os.chdir(self._original_directory)
