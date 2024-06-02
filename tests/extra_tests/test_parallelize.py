# -*- coding: utf-8 -*-

import builtins
import os
import sys
import pytest

from typing import Any, Iterator

from click.testing import CliRunner

from src import __version__
from src.__main__ import climain
from src.dir_context import DirContext

from helpers import FileSystemPath, open_utf8
from fixtures_main import (
    TEST_FILE_CONTENTS,
    filesystem,  # pyright: ignore [reportUnusedImport]
)


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


def test_parallelization_full_run_one_surviving_mutant(
    filesystem: FileSystemPath,
) -> None:
    with open(os.path.join(str(filesystem), "tests", "test_foo.py"), "w") as f:
        f.write(TEST_FILE_CONTENTS.replace("assert foo(2, 2) is False", ""))

    result = CliRunner().invoke(
        climain,
        ["run", "--paths-to-mutate=foo.py", "--test-time-base=15.0", "--parallelize"],
        catch_exceptions=False,
    )
    print(repr(result.output))
    assert result.exit_code == 2

    result = CliRunner().invoke(climain, ["results"], catch_exceptions=False)
    print(repr(result.output))
    assert result.exit_code == 0
    assert (
        result.output.strip()
        == """
To apply a mutant on disk:
    mutmut apply <id>

To show a mutant:
    mutmut show <id>


Survived 🙁 (1)

---- foo.py (1) ----

1
""".strip()
    )
