# -*- coding: utf-8 -*-

import builtins
import os
from os.path import join
from pathlib import Path
from typing import Iterator

import pytest

from helpers import FileSystemPath, open_utf8


builtins.open = open_utf8  # type: ignore [assignment]


@pytest.fixture
def surviving_mutants_filesystem(tmpdir: FileSystemPath) -> Iterator[Path]:
    foo_py = """
def foo(a, b):
    result = a + b
    return result
"""

    test_py = """
def test_nothing(): assert True
"""

    create_filesystem(tmpdir, foo_py, test_py)

    yield tmpdir


def create_filesystem(
    tmpdir: FileSystemPath, file_to_mutate_contents: str, test_file_contents: str
) -> None:
    test_dir = str(tmpdir)
    os.chdir(test_dir)

    # hammett is almost 5x faster than pytest. Let's use that instead.
    with open(join(test_dir, "setup.cfg"), "w") as f:
        f.write(
            """
[mutmut]
runner=python -m hammett -x
"""
        )

    with open(join(test_dir, "foo.py"), "w") as f:
        f.write(file_to_mutate_contents)

    os.mkdir(join(test_dir, "tests"))

    with open(join(test_dir, "tests", "test_foo.py"), "w") as f:
        f.write(test_file_contents)
