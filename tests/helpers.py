import builtins
from pathlib import Path
from typing import Any

from src.shared import FilenameStr


class FileSystemPath(Path):
    """Only for type checking"""

    # it's actually a pytest LocalPath, API is similar but not exactly the same
    # more info: https://stackoverflow.com/questions/40784950/pathlib-path-and-py-test-localpath

    def write(self, text: str) -> None: ...


# fix open to use unicode


original_open = builtins.open


def open_utf8(
    filename: FilenameStr,
    mode: str = "r",
    *,
    encoding: str | None = None,
    **kwargs: Any
) -> Any:
    if "b" not in mode:
        encoding = encoding if encoding is not None else "utf-8"
    return original_open(filename, mode, encoding=encoding, **kwargs)
