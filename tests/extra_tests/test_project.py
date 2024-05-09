import os
from typing import Iterator
from click.testing import CliRunner
import pytest

from mutmut.__main__ import climain

from helpers import FileSystemPath


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
    test_file.write("""
from foo import add

def test_add():
    assert add(1, 1) == 2
""")
    original = os.getcwd()
    os.chdir(dir_a)
    yield tmpdir
    os.chdir(original)

def test_project_path(filesystem_with_two_dirs: FileSystemPath) -> None:
    result_run = CliRunner().invoke(climain, ['run', '--paths-to-mutate=foo.py', '--project=../b'], catch_exceptions=False)
    result_show = CliRunner().invoke(climain, ['show', '1', '--project=../b'], catch_exceptions=False)
    assert '1/1  🎉 1  ⏰ 0  🤔 0  🙁 0  🔇 0' in result_run.output
    assert result_run.exit_code == 0
    assert '''
--- foo.py
+++ foo.py
@@ -1 +1 @@
-def add(a, b): return a + b
+def add(a, b): return a - b
'''.strip() in result_show.output
