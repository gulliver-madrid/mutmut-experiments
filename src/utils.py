# -*- coding: utf-8 -*-

import itertools
import os
import shutil
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Callable

from src.dir_context import DirContext


def ranges(numbers: Sequence[int]) -> str:
    if not numbers:
        return ""

    result: list[str] = []
    start_range = numbers[0]
    end_range = numbers[0]

    def add_result() -> None:
        if start_range == end_range:
            result.append(str(start_range))
        else:
            result.append("{}-{}".format(start_range, end_range))

    for x in numbers[1:]:
        if end_range + 1 == x:
            end_range = x
        else:
            add_result()

            start_range = x
            end_range = x

    add_result()

    return ", ".join(result)


def split_paths(paths: str, directory: Path) -> list[str]:
    # This method is used to split paths that are separated by commas or colons
    # filtering out those that do not exist
    separated: list[str] | None = None
    for sep in [",", ":"]:
        if sep in paths:
            separated = paths.split(sep)
            break
    else:
        separated = [paths]
    return filter_not_existing(separated, directory)


def filter_not_existing(paths: list[str], directory: Path) -> list[str]:
    # filter paths that do not exist
    with DirContext(directory):
        return list(filter(lambda p: Path(p).exists(), paths))


spinner = itertools.cycle("⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏")


def status_printer() -> Callable[[str], None]:
    """Manage the printing and in-place updating of a line of characters

    .. note::
        If the string is longer than a line, then in-place updating may not
        work (it will print a new line at each refresh).
    """
    last_len = [0]

    def p(s: str) -> None:
        s = next(spinner) + " " + s
        len_s = len(s)
        output = "\r" + s + (" " * max(last_len[0] - len_s, 0))
        sys.stdout.write(output)
        sys.stdout.flush()
        last_len[0] = len_s

    return p


def split_lines(s: str) -> list[str]:
    return s.split("\n")


print_status = status_printer()


def copy_directory(src: str, dst: str) -> None:
    for item in os.listdir(src):
        if item.startswith(".") or item in [
            "pyproject.toml",
            "poetry.lock",
            "html",
            "__pycache__",
        ]:
            continue
        if item.isdigit():
            # mutation subdirectories
            continue
        s = os.path.join(src, item)
        d = os.path.join(dst, item)
        if os.path.isdir(s):
            shutil.copytree(s, d, dirs_exist_ok=True)
        else:
            shutil.copy2(s, d)
