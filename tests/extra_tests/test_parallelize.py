# -*- coding: utf-8 -*-

import builtins
import sys
import pytest

from typing import Any, Iterator

from click.testing import CliRunner

from src import (
    __version__,
)
from src.__main__ import climain

from helpers import FileSystemPath, open_utf8
from src.dir_context import DirContext


builtins.open = open_utf8  # type: ignore [assignment]


@pytest.fixture
def simple_filesystem(tmpdir: FileSystemPath) -> Iterator[FileSystemPath]:
    source_file = tmpdir / "foo.py"
    source_file.write("def add(a, b): return a + b")
    tests_dir = tmpdir / "tests"
    tests_dir.mkdir()
    test_file = tests_dir / "test_foo.py"
    test_file.write(
        """
from foo import add

def test_add():
    assert add(1, 1) == 2
"""
    )

    yield tmpdir


@pytest.fixture
def set_working_dir_and_path_parallelize(
    simple_filesystem: FileSystemPath,
) -> Iterator[FileSystemPath]:

    original_path = sys.path[:]

    with DirContext(simple_filesystem):
        if str(simple_filesystem) in sys.path:
            sys.path.remove(str(simple_filesystem))

        yield simple_filesystem

        sys.path = original_path


def test_parallelization_run(set_working_dir_and_path_parallelize: Any) -> None:
    result_run = CliRunner().invoke(
        climain,
        ["run", "--paths-to-mutate=foo.py", "--parallelize"],
        catch_exceptions=False,
    )
    print(f"{(result_run.output)=}")
    print(result_run.output)
    print("Done")
    assert "1/1  🎉 1  ⏰ 0  🤔 0  🙁 0  🔇 0" in result_run.output
    assert result_run.exit_code == 0

    result_show = CliRunner().invoke(climain, ["show", "1"], catch_exceptions=False)

    assert (
        """
--- foo.py
+++ foo.py
@@ -1 +1 @@
-def add(a, b): return a + b
+def add(a, b): return a - b
""".strip()
        in result_show.output
    )
