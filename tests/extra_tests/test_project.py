import os
from pathlib import Path
from typing import Iterator
from click.testing import CliRunner
import pytest

from src.__main__ import climain

from helpers import FileSystemPath
from src.dir_context import DirContext


@pytest.fixture
def filesystem_with_two_dirs(tmpdir: FileSystemPath) -> Iterator[FileSystemPath]:
    dir_a = tmpdir / "a"
    dir_b = tmpdir / "b"
    dir_a.mkdir()
    dir_b.mkdir()
    source_file = dir_b / "foo.py"
    source_file.write("def add(a, b): return a + b")
    tests_dir = dir_b / "tests"
    tests_dir.mkdir()
    test_file = tests_dir / "test_foo.py"
    test_file.write(
        """
from foo import add

def test_add():
    assert add(1, 1) == 2
"""
    )
    with DirContext(dir_a):
        yield tmpdir


def test_project_path_run(filesystem_with_two_dirs: FileSystemPath) -> None:
    dir_b = (Path(os.getcwd()) / ".." / "b").resolve()
    assert dir_b.exists()
    assert dir_b.is_absolute()
    result_run = CliRunner().invoke(
        climain,
        ["run", "--paths-to-mutate=foo.py", f"--project={str(dir_b)}"],
        catch_exceptions=False,
    )
    result_show = CliRunner().invoke(
        climain, ["show", "1", f"--project={str(dir_b)}"], catch_exceptions=False
    )
    assert "1/1  🎉 1  ⏰ 0  🤔 0  🙁 0  🔇 0" in result_run.output
    assert result_run.exit_code == 0
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


def test_project_path_show_or_apply_without_run(
    filesystem_with_two_dirs: FileSystemPath,
) -> None:
    for command in ("show", "apply"):
        result_show = CliRunner().invoke(
            climain, [command, "1", "--project=../b"], catch_exceptions=False
        )
        assert result_show.exit_code == 1
        assert "There is no" in result_show.output


def test_project_path_run_and_apply(filesystem_with_two_dirs: FileSystemPath) -> None:
    CliRunner().invoke(
        climain,
        ["run", "--paths-to-mutate=foo.py", "--project=../b"],
        catch_exceptions=False,
    )
    result_apply = CliRunner().invoke(
        climain, ["apply", "1", "--project=../b"], catch_exceptions=False
    )
    assert result_apply.exit_code == 0
    with open("../b/foo.py", "r") as file:
        assert file.read().strip() == "def add(a, b): return a - b"
