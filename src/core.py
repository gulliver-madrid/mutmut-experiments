# -*- coding: utf-8 -*-
from __future__ import annotations

import fnmatch
import os
import sys
from configparser import ConfigParser
from functools import wraps
from io import open
from os.path import isdir
from pathlib import Path
from typing import (
    Any,
    Callable,
    Iterator,
    Optional,
    ParamSpec,
    cast,
)

import toml

from src.cache.cache import MutationsByFile
from src.config import Config
from src.context import Context
from src.dir_context import DirContext
from src.mutate import list_mutations
from src.progress import Progress
from src.tools import configure_logger
from src.shared import FilenameStr
from src.storage import storage
from src.utils import SequenceStr


__version__ = "2.5.0"

logger = configure_logger(__name__)


P = ParamSpec("P")


def config_from_file(
    **defaults: Any,
) -> Callable[[Callable[P, None]], Callable[P, None]]:
    """
    Creates a decorator that loads configurations from pyproject.toml and setup.cfg and applies
    these configurations to other functions that are declared with it.
    """
    project = os.getcwd()
    found = False
    for i, arg in enumerate(sys.argv):
        if found:
            break
        for preffix in ("-p", "--project"):
            if arg[: len(preffix)] == preffix:
                if "=" in arg:
                    _, project = arg.split("=")
                else:
                    project = sys.argv[i + 1]
                project = project.strip()
                assert Path(project).exists()
                found = True
                break

    def config_from_pyproject_toml() -> dict[str, object]:
        with DirContext(project):
            try:
                data = toml.load("pyproject.toml")["tool"]["mutmut"]
                assert isinstance(data, dict)
                return cast(dict[str, object], data)
            except (FileNotFoundError, KeyError):
                return {}
            except Exception as err:
                raise RuntimeError(
                    "Error trying to read mutation config from pyproject.toml"
                ) from err

    def config_from_setup_cfg() -> dict[str, object]:
        with DirContext(project):
            config_parser = ConfigParser()
            config_parser.read("setup.cfg")

            try:
                return dict(config_parser["mutmut"])
            except KeyError:
                return {}

    config = config_from_pyproject_toml() or config_from_setup_cfg()

    def decorator(f: Callable[P, None]) -> Callable[P, None]:
        @wraps(f)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> None:
            for k in list(kwargs.keys()):
                if not kwargs[k]:
                    kwargs[k] = config.get(k, defaults.get(k))
            f(*args, **kwargs)

        return wrapper

    return decorator


def guess_paths_to_mutate() -> str:
    """Guess the path to source code to mutate"""
    project_dir = storage.project_path.get_current_project_path()
    project_dir_name = str(project_dir).split(os.sep)[-1]

    with DirContext(project_dir_name):
        result: str | None = None
        if isdir("lib"):
            result = "lib"
        elif isdir("src"):
            result = "src"
        elif isdir(project_dir_name):
            result = project_dir_name
        elif isdir(project_dir_name.replace("-", "_")):
            result = project_dir_name.replace("-", "_")
        elif isdir(project_dir_name.replace(" ", "_")):
            result = project_dir_name.replace(" ", "_")
        elif isdir(project_dir_name.replace("-", "")):
            result = project_dir_name.replace("-", "")
        elif isdir(project_dir_name.replace(" ", "")):
            result = project_dir_name.replace(" ", "")

    if result is None:
        raise FileNotFoundError(
            "Could not figure out where the code to mutate is. "
            "Please specify it on the command line using --paths-to-mutate, "
            'or by adding "paths_to_mutate=code_dir" in pyproject.toml or setup.cfg to the [mutmut] '
            "section."
        )
    return result


def add_mutations_by_file(
    mutations_by_file: MutationsByFile,
    filename: FilenameStr,
    dict_synonyms: SequenceStr,
    config: Optional[Config],
) -> None:
    with open(filename) as f:
        source = f.read()
    context = Context(
        source=source,
        filename=filename,
        config=config,
        dict_synonyms=dict_synonyms,
    )

    try:
        mutations_by_file[filename] = list_mutations(context)
        from src.cache.cache import register_mutants

        register_mutants(mutations_by_file)
    except Exception as e:
        raise RuntimeError(
            'Failed while creating mutations for {}, for line "{}": {}'.format(
                context.filename, context.current_source_line, e
            )
        ) from e


def python_source_files(
    path: Path, tests_dirs: SequenceStr, paths_to_exclude: Optional[SequenceStr] = None
) -> Iterator[FilenameStr]:
    """Attempt to guess where the python source files to mutate are and yield
    their paths

    :param path: path to a python source file or package directory
    :param tests_dirs: list of directory paths containing test files
        (we do not want to mutate these!)
    :param paths_to_exclude: list of UNIX filename patterns to exclude

    :return: generator listing the paths to the python source files to mutate (absolute paths!)
    """
    if path.is_absolute():
        parent = storage.project_path.get_current_project_path().resolve()
        child = path.resolve()
        assert child == parent or parent in child.parents, (child, parent)
        absolute_path = path
    else:
        absolute_path = (
            storage.project_path.get_current_project_path() / path
        ).resolve()
    assert absolute_path.exists(), absolute_path
    relative_path = absolute_path.relative_to(
        storage.project_path.get_current_project_path()
    )
    # TODO: review if exclusion works with file paths
    paths_to_exclude = paths_to_exclude or []
    with DirContext(storage.project_path.get_current_project_path()):
        if absolute_path.is_dir():
            for root, dirs, files_ in os.walk(relative_path, topdown=True):
                files = cast(list[FilenameStr], files_)
                for exclude_pattern in paths_to_exclude:
                    dirs[:] = [
                        d for d in dirs if not fnmatch.fnmatch(d, exclude_pattern)
                    ]
                    files[:] = [
                        f for f in files if not fnmatch.fnmatch(f, exclude_pattern)
                    ]

                dirs[:] = [d for d in dirs if os.path.join(root, d) not in tests_dirs]
                for filename in files:
                    if filename.endswith(".py"):
                        yield FilenameStr(os.path.join(root, filename))
        else:
            yield FilenameStr(str(relative_path))


def compute_exit_code(
    progress: Progress, exception: Optional[Exception] = None, ci: bool = False
) -> int:
    """Compute an exit code for mutmut mutation testing

    The following exit codes are available for mutmut (as documented for the CLI run command):
     * 0 if all mutants were killed (OK_KILLED)
     * 1 if a fatal error occurred
     * 2 if one or more mutants survived (BAD_SURVIVED)
     * 4 if one or more mutants timed out (BAD_TIMEOUT)
     * 8 if one or more mutants caused tests to take twice as long (OK_SUSPICIOUS)

     Exit codes 1 to 8 will be bit-ORed so that it is possible to know what
     different mutant statuses occurred during mutation testing.

     When running with ci=True (--CI flag enabled), the exit code will always be
     1 for a fatal error or 0 for any other case.

    :param exception:
    :param progress:
    :param ci:

    :return: integer noting the exit code of the mutation tests.
    """
    code = 0
    if exception is not None:
        code = code | 1
    if ci:
        return code
    if progress.surviving_mutants > 0:
        code = code | 2
    if progress.surviving_mutants_timeout > 0:
        code = code | 4
    if progress.suspicious_mutants > 0:
        code = code | 8
    return code
