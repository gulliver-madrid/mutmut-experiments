import builtins
from pathlib import Path
from typing import Any

FileSystemPath = Path  # it's actually a pytest LocalPath, API is similar but not exactly the same
# more info: https://stackoverflow.com/questions/40784950/pathlib-path-and-py-test-localpath

# fix open to use unicode

original_open = builtins.open


def open_utf8(filename: str, mode: str = 'r', *, encoding: str | None = None, **kwargs: Any) -> Any:
    if 'b' not in mode:
        encoding = encoding if encoding is not None else 'utf-8'
    return original_open(filename, mode, encoding=encoding, **kwargs)
