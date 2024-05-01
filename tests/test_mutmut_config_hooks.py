import os
import sys
import subprocess

import pytest

from helpers import FileSystemPath


@pytest.fixture
def basic_filesystem(tmpdir: FileSystemPath):
    source_file = tmpdir / "foo.py"
    source_file.write("def add(a, b): return a + b")
    tests_dir = tmpdir / "tests"
    tests_dir.mkdir()
    test_file = tests_dir / "test_foo.py"
    test_file.write("""
from foo import add

def test_add():
    assert add(1, 1) == 2
""")
    mutmut_config_py = tmpdir / "mutmut_config.py"
    mutmut_config_py.write("""
from pathlib import Path

def init():
    Path("init_hook").touch()

def pre_mutation(context):
    Path("pre_mutation_hook").touch()

def pre_mutation_ast(context):
    Path("pre_mutation_ast_hook").touch()
""")
    yield tmpdir


@pytest.fixture
def set_working_dir_and_path(basic_filesystem: FileSystemPath):
    original_dir = os.path.abspath(os.getcwd())
    original_path = sys.path[:]

    os.chdir(basic_filesystem)
    if str(basic_filesystem) in sys.path:
        sys.path.remove(str(basic_filesystem))

    yield basic_filesystem

    sys.path = original_path
    os.chdir(original_dir)

# En este test, aparece el error "No module named mutmut" en el stderr
# Por algun motivo aqui se usa python -m mutmut run, en vez de simplemente
# run como en otros tests.
# Pero cambiando eso sale el error: FileNotFoundError: [WinError 2] El sistema no puede encontrar el archivo especificado


@pytest.mark.xfail(reason="unknown reason, probably mutmut not found")
@pytest.mark.usefixtures("set_working_dir_and_path")
def test_hooks(basic_filesystem: FileSystemPath):
    try:
        subprocess.check_output(["python", "-m", "mutmut", "run", "--paths-to-mutate=foo.py"])
    except subprocess.CalledProcessError as e:
        print(e.output)
        assert False, f"Hubo un error llamando a subprocess: {e.output}"
    assert (basic_filesystem / "init_hook").exists(), "init was not called."
    assert (basic_filesystem / "pre_mutation_hook").exists(), "pre_mutation was not called."
    assert (basic_filesystem / "pre_mutation_ast_hook").exists(), "pre_mutation_ast was not called."
