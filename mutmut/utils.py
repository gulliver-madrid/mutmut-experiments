# -*- coding: utf-8 -*-

import itertools
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Callable


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
            result.append('{}-{}'.format(start_range, end_range))

    for x in numbers[1:]:
        if end_range + 1 == x:
            end_range = x
        else:
            add_result()

            start_range = x
            end_range = x

    add_result()

    return ', '.join(result)


def split_paths(paths: str) -> list[str] | None:
    # This method is used to split paths that are separated by commas or colons
    # filtering out those that do not exist
    for sep in [',', ':']:
        separated = list(filter(lambda p: Path(p).exists(), paths.split(sep)))
        if separated:
            return separated
    return None


spinner = itertools.cycle('⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏')


def status_printer() -> Callable[[str], None]:
    """Manage the printing and in-place updating of a line of characters

    .. note::
        If the string is longer than a line, then in-place updating may not
        work (it will print a new line at each refresh).
    """
    last_len = [0]

    def p(s: str) -> None:
        s = next(spinner) + ' ' + s
        len_s = len(s)
        output = '\r' + s + (' ' * max(last_len[0] - len_s, 0))
        sys.stdout.write(output)
        sys.stdout.flush()
        last_len[0] = len_s
    return p


def split_lines(s: str) -> list[str]:
    return s.split('\n')
