import os
import sys
from typing import Any, Iterator

from click.testing import CliRunner
import pytest

from helpers import FileSystemPath
from src.__main__ import climain
from src.dynamic_config_storage import DYNAMIC_CONFIG_FILENAME


@pytest.fixture
def basic_filesystem(tmpdir: FileSystemPath) -> Iterator[FileSystemPath]:
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
    dynamic_config_path = tmpdir / DYNAMIC_CONFIG_FILENAME
    dynamic_config_path.write(
        """
from pathlib import Path

def init():
    Path("init_hook").touch()

def pre_mutation(context):
    Path("pre_mutation_hook").touch()

def pre_mutation_ast(context):
    Path("pre_mutation_ast_hook").touch()
"""
    )
    yield tmpdir


@pytest.fixture
def set_working_dir_and_path(request: Any) -> Iterator[FileSystemPath]:

    def get_default() -> FileSystemPath:
        return request.getfixturevalue("basic_filesystem")  # type: ignore [no-any-return]

    if hasattr(request, "param"):
        basic_filesystem = request.param
    else:
        basic_filesystem = get_default()

    original_dir = os.path.abspath(os.getcwd())
    original_path = sys.path[:]

    os.chdir(basic_filesystem)
    if str(basic_filesystem) in sys.path:
        sys.path.remove(str(basic_filesystem))

    yield basic_filesystem

    sys.path = original_path
    os.chdir(original_dir)


@pytest.mark.usefixtures("set_working_dir_and_path")
def test_hooks(basic_filesystem: FileSystemPath) -> None:
    result = CliRunner().invoke(
        climain, ["run", "--paths-to-mutate=foo.py"], catch_exceptions=False
    )
    assert result.exit_code == 0
    assert (basic_filesystem / "init_hook").exists(), "init was not called."
    assert (
        basic_filesystem / "pre_mutation_hook"
    ).exists(), "pre_mutation was not called."
    assert (
        basic_filesystem / "pre_mutation_ast_hook"
    ).exists(), "pre_mutation_ast was not called."
