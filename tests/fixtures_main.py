# -*- coding: utf-8 -*-
import pytest

from pathlib import Path
from typing import Iterator

from fixtures import create_filesystem
from helpers import FileSystemPath


FILE_TO_MUTATE_LINES = [
    "def foo(a, b):",
    "    return a < b",
    "c = 1",
    "c += 1",
    "e = 1",
    "f = 3",
    "d = dict(e=f)",
    "g: int = 2",
]

FILE_TO_MUTATE_CONTENTS = "\n".join(FILE_TO_MUTATE_LINES) + "\n"

TEST_FILE_CONTENTS = """
from foo import *

def test_foo():
   assert foo(1, 2) is True
   assert foo(2, 2) is False

   assert c == 2
   assert e == 1
   assert f == 3
   assert d == dict(e=f)
   assert g == 2
"""


@pytest.fixture
def filesystem(tmpdir: FileSystemPath) -> Iterator[Path]:
    create_filesystem(tmpdir, FILE_TO_MUTATE_CONTENTS, TEST_FILE_CONTENTS)

    yield tmpdir
