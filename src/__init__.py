# -*- coding: utf-8 -*-
from __future__ import annotations

import fnmatch
import multiprocessing
import os
from pathlib import Path
import shlex
import subprocess
import sys
from configparser import ConfigParser
from copy import copy as copy_obj
from functools import wraps
from io import open, TextIOBase
from multiprocessing.context import SpawnProcess
from os.path import isdir
from shutil import move, copy
from threading import Thread
from time import time
from typing import (
    Any,
    Callable,
    Dict,
    Iterator,
    List,
    Literal,
    Optional,
    ParamSpec,
    Tuple,
    TypeAlias,
    cast,
)

import toml

from src.config import Config
from src.context import Context, RelativeMutationID
from src.mut_config_storage import user_dynamic_config_storage
from src.mutate import list_mutations, mutate_from_context
from src.process import popen_streaming_output
from src.progress import Progress
from src.project import ProjectPath, project_path_storage
from src.mutations import SkipException
from src.setup_logging import configure_logger
from src.status import (
    BAD_SURVIVED,
    BAD_TIMEOUT,
    OK_KILLED,
    OK_SUSPICIOUS,
    SKIPPED,
    UNTESTED,
    StatusResultStr,
)


__version__ = "2.5.0"

logger = configure_logger(__name__)


StrConsumer = Callable[[str], None]


def mutate_file(backup: bool, context: Context) -> Tuple[str, str]:
    assert isinstance(context.filename, str)
    with open(project_path_storage.get_current_project_path() / context.filename) as f:
        original = f.read()
    if backup:
        with open(
            project_path_storage.get_current_project_path()
            / (context.filename + ".bak"),
            "w",
        ) as f:
            f.write(original)
    mutated, _ = mutate_from_context(context)
    with open(
        project_path_storage.get_current_project_path() / context.filename, "w"
    ) as f:
        f.write(mutated)
    return original, mutated


MutantQueueItem: TypeAlias = (
    tuple[Literal["mutant"], Context] | tuple[Literal["end"], None]
)
MutantQueue: TypeAlias = "multiprocessing.Queue[MutantQueueItem]"


def queue_mutants(
    *,
    progress: Progress,
    config: Config,
    mutants_queue: MutantQueue,
    mutations_by_file: Dict[str, List[RelativeMutationID]],
    project: ProjectPath | None = None,
) -> None:
    from src.cache.cache import get_cached_mutation_statuses

    project_path_storage.set_project_path(project)

    try:
        index = 0
        for filename, mutations in mutations_by_file.items():
            cached_mutation_statuses = get_cached_mutation_statuses(
                filename, mutations, config.hash_of_tests
            )
            with open(project_path_storage.get_current_project_path() / filename) as f:
                source = f.read()
            for mutation_id in mutations:
                cached_status = cached_mutation_statuses.get(mutation_id)
                assert isinstance(cached_status, str)
                if cached_status != UNTESTED:
                    progress.register(cached_status)
                    continue
                context = Context(
                    mutation_id=mutation_id,
                    filename=filename,
                    dict_synonyms=config.dict_synonyms,
                    config=copy_obj(config),
                    source=source,
                    index=index,
                )
                mutants_queue.put(("mutant", context))
                index += 1
    finally:
        mutants_queue.put(("end", None))


ResultQueueItem: TypeAlias = (
    tuple[Literal["status"], str, str | None, RelativeMutationID]
    | tuple[Literal["progress"], str, None, None]
    | tuple[Literal["end", "cycle"], None, None, None]
)
ResultQueue: TypeAlias = "multiprocessing.Queue[ResultQueueItem]"


def check_mutants(
    mutants_queue: MutantQueue,
    results_queue: ResultQueue,
    cycle_process_after: int,
    project_path: ProjectPath | None = None,
) -> None:
    assert isinstance(cycle_process_after, int)

    # We want be sure than when mutation tests get called, mutmut_config.py is obtained again.
    # If not, executing tests after mutmut_config is set could prevent to get a new mutmut_config
    # if directory has changed.
    # This is probably not really needed in the regular program flow (that uses spawn).
    # More info: https://stackoverflow.com/questions/64095876/multiprocessing-fork-vs-spawn
    user_dynamic_config_storage.clear_mutmut_config_cache()

    def feedback(line: str) -> None:
        results_queue.put(("progress", line, None, None))

    did_cycle = False

    try:
        count = 0
        while True:
            command, context = mutants_queue.get()
            if command == "end":
                break

            assert context
            status = run_mutation(context, feedback, project_path)
            results_queue.put(("status", status, context.filename, context.mutation_id))
            count += 1
            if count == cycle_process_after:
                results_queue.put(("cycle", None, None, None))
                did_cycle = True
                break
    finally:
        if not did_cycle:
            results_queue.put(("end", None, None, None))


def run_mutation(
    context: Context, callback: StrConsumer, project_path: ProjectPath | None = None
) -> StatusResultStr:
    """
    :return: (computed or cached) status of the tested mutant, one of mutant_statuses
    """
    from src.cache.cache import cached_mutation_status

    assert context.config is not None
    assert context.filename is not None
    if project_path is not None:
        project_path_storage.set_project_path(project_path)
    os.chdir(project_path_storage.get_current_project_path())
    mutmut_config = user_dynamic_config_storage.get_mutmut_config()
    cached_status = cached_mutation_status(
        context.filename, context.mutation_id, context.config.hash_of_tests
    )

    if cached_status != UNTESTED and context.config.total != 1:
        return cached_status

    config = context.config
    if mutmut_config is not None and hasattr(mutmut_config, "pre_mutation"):
        context.current_line_index = context.mutation_id.line_number
        try:
            mutmut_config.pre_mutation(context=context)
        except SkipException:
            return SKIPPED
        if context.skip:
            return SKIPPED

    if config.pre_mutation:
        result = (
            subprocess.check_output(config.pre_mutation, shell=True).decode().strip()
        )
        if result and not config.swallow_output:
            callback(result)

    try:
        mutate_file(backup=True, context=context)
        start = time()
        try:
            survived = tests_pass(config=config, callback=callback)
            if (
                survived
                and config.test_command != config.default_test_command
                and config.rerun_all
            ):
                # rerun the whole test suite to be sure the mutant can not be killed by other tests
                config.test_command = config.default_test_command
                survived = tests_pass(config=config, callback=callback)
        except TimeoutError:
            return BAD_TIMEOUT

        time_elapsed = time() - start
        if not survived and time_elapsed > config.test_time_base + (
            config.baseline_time_elapsed * config.test_time_multiplier
        ):
            return OK_SUSPICIOUS

        if survived:
            return BAD_SURVIVED
        else:
            return OK_KILLED
    except SkipException:
        return SKIPPED

    finally:
        assert isinstance(context.filename, str)
        original = os.getcwd()
        os.chdir(project_path_storage.get_current_project_path())
        move(context.filename + ".bak", context.filename)
        os.chdir(original)
        config.test_command = (
            config.default_test_command
        )  # reset test command to its default in the case it was altered in a hook
        if config.post_mutation:
            result = (
                subprocess.check_output(config.post_mutation, shell=True)
                .decode()
                .strip()
            )
            if result and not config.swallow_output:
                callback(result)


def tests_pass(config: Config, callback: StrConsumer) -> bool:
    """
    :return: :obj:`True` if the tests pass, otherwise :obj:`False`
    """
    if config.using_testmon:
        copy(".testmondata-initial", ".testmondata")

    use_special_case = True

    # Special case for hammett! We can do in-process test running which is much faster
    if use_special_case and config.test_command.startswith(hammett_prefix):
        return hammett_tests_pass(config, callback)

    returncode = popen_streaming_output(
        config.test_command, callback, timeout=config.baseline_time_elapsed * 10
    )
    return returncode != 1


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
        original = os.getcwd()
        os.chdir(project)
        try:
            data = toml.load("pyproject.toml")["tool"]["mutmut"]
            assert isinstance(data, dict)
            return cast(dict[str, object], data)
        except (FileNotFoundError, KeyError):
            return {}
        finally:
            os.chdir(original)

    def config_from_setup_cfg() -> dict[str, object]:
        original = os.getcwd()
        os.chdir(project)
        config_parser = ConfigParser()
        config_parser.read("setup.cfg")

        try:
            return dict(config_parser["mutmut"])
        except KeyError:
            return {}
        finally:
            os.chdir(original)

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
    project_dir = project_path_storage.get_current_project_path()
    project_dir_name = str(project_dir).split(os.sep)[-1]
    original = os.getcwd()
    os.chdir(project_dir_name)
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
    os.chdir(original)
    if result is None:
        raise FileNotFoundError(
            "Could not figure out where the code to mutate is. "
            "Please specify it on the command line using --paths-to-mutate, "
            'or by adding "paths_to_mutate=code_dir" in pyproject.toml or setup.cfg to the [mutmut] '
            "section."
        )
    return result


def get_mutations_by_file_from_cache(
    mutation_pk: Any,
) -> dict[str, list[RelativeMutationID]]:
    """No code uses this function"""
    from src.cache.cache import filename_and_mutation_id_from_pk

    filename, mutation_id = filename_and_mutation_id_from_pk(int(mutation_pk))
    return {filename: [mutation_id]}


def hammett_tests_pass(config: Config, callback: StrConsumer) -> bool:
    # noinspection PyUnresolvedReferences
    from hammett import main_cli  # type: ignore [import-untyped]

    modules_before = set(sys.modules.keys())

    # set up timeout
    import _thread
    from threading import (
        Timer,
        current_thread,
        main_thread,
    )

    timed_out = False

    def timeout() -> None:
        _thread.interrupt_main()
        nonlocal timed_out
        timed_out = True

    assert current_thread() is main_thread()
    timer = Timer(config.baseline_time_elapsed * 10, timeout)
    timer.daemon = True
    timer.start()

    # Run tests
    try:

        class StdOutRedirect(TextIOBase):
            def write(self, s: str) -> int:
                callback(s)
                return len(s)

        redirect = StdOutRedirect()
        sys.stdout = redirect  # type: ignore [assignment]
        sys.stderr = redirect  # type: ignore [assignment]
        returncode = main_cli(shlex.split(config.test_command[len(hammett_prefix) :]))
        sys.stdout = sys.__stdout__
        sys.stderr = sys.__stderr__
        timer.cancel()
    except KeyboardInterrupt:
        timer.cancel()
        if timed_out:
            raise TimeoutError("In process tests timed out")
        raise

    modules_to_force_unload = {
        x.partition(os.sep)[0].replace(".py", "") for x in config.paths_to_mutate
    }

    for module_name in sorted(
        set(sys.modules.keys()) - set(modules_before), reverse=True
    ):
        if (
            any(module_name.startswith(x) for x in modules_to_force_unload)
            or module_name.startswith("tests")
            or module_name.startswith("django")
        ):
            del sys.modules[module_name]

    return bool(returncode == 0)


CYCLE_PROCESS_AFTER = 100


class MutationTestsRunner:
    def __init__(self) -> None:
        # List of active multiprocessing queues
        self._active_queues: list["multiprocessing.Queue[Any]"] = []

    def run_mutation_tests(
        self,
        config: Config,
        progress: Progress,
        mutations_by_file: Dict[str, List[RelativeMutationID]] | None,
        *,
        project_path: ProjectPath | None = None,
    ) -> None:
        from src.cache.cache import update_mutant_status

        # Need to explicitly use the spawn method for python < 3.8 on macOS
        mp_ctx = multiprocessing.get_context("spawn")

        mutants_queue = mp_ctx.Queue(maxsize=100)
        self.add_to_active_queues(mutants_queue)

        queue_mutants_thread = Thread(
            target=queue_mutants,
            name="queue_mutants",
            daemon=True,
            kwargs=dict(
                progress=progress,
                config=config,
                mutants_queue=mutants_queue,
                mutations_by_file=mutations_by_file,
                project=project_path_storage.get_current_project_path(),
            ),
        )

        queue_mutants_thread.start()

        results_queue = mp_ctx.Queue(maxsize=100)
        self.add_to_active_queues(results_queue)

        def create_worker() -> SpawnProcess:
            t = mp_ctx.Process(
                target=check_mutants,
                name="check_mutants",
                daemon=True,
                kwargs=dict(
                    mutants_queue=mutants_queue,
                    results_queue=results_queue,
                    cycle_process_after=CYCLE_PROCESS_AFTER,
                    project_path=project_path,
                ),
            )
            t.start()
            return t

        t = create_worker()

        while True:
            command, status, filename, mutation_id = results_queue.get()
            if command == "end":
                t.join()
                break

            elif command == "cycle":
                t = create_worker()

            elif command == "progress":
                if not config.swallow_output:
                    print(status, end="", flush=True)
                elif not config.no_progress:
                    progress.print()

            else:
                assert command == "status"

                progress.register(status)

                update_mutant_status(
                    file_to_mutate=filename,
                    mutation_id=mutation_id,
                    status=status,
                    tests_hash=config.hash_of_tests,
                )

    def add_to_active_queues(self, queue: "multiprocessing.Queue[Any]") -> None:
        self._active_queues.append(queue)

    def close_active_queues(self) -> None:
        for queue in self._active_queues:
            queue.close()


def add_mutations_by_file(
    mutations_by_file: Dict[str, List[RelativeMutationID]],
    filename: str,
    dict_synonyms: List[str],
    config: Optional[Config],
) -> None:
    assert isinstance(dict_synonyms, list)
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
    path: Path, tests_dirs: List[str], paths_to_exclude: Optional[List[str]] = None
) -> Iterator[str]:
    """Attempt to guess where the python source files to mutate are and yield
    their paths

    :param path: path to a python source file or package directory
    :param tests_dirs: list of directory paths containing test files
        (we do not want to mutate these!)
    :param paths_to_exclude: list of UNIX filename patterns to exclude

    :return: generator listing the paths to the python source files to mutate (absolute paths!)
    """
    if path.is_absolute():
        parent = project_path_storage.get_current_project_path().resolve()
        child = path.resolve()
        assert child == parent or parent in child.parents, (child, parent)
        absolute_path = path
    else:
        absolute_path = (
            project_path_storage.get_current_project_path() / path
        ).resolve()
    assert absolute_path.exists(), absolute_path
    relative_path = absolute_path.relative_to(
        project_path_storage.get_current_project_path()
    )
    paths_to_exclude = paths_to_exclude or []
    original = os.getcwd()
    os.chdir(project_path_storage.get_current_project_path())
    if absolute_path.is_dir():
        for root, dirs, files in os.walk(relative_path, topdown=True):
            for exclude_pattern in paths_to_exclude:
                dirs[:] = [d for d in dirs if not fnmatch.fnmatch(d, exclude_pattern)]
                files[:] = [f for f in files if not fnmatch.fnmatch(f, exclude_pattern)]

            dirs[:] = [d for d in dirs if os.path.join(root, d) not in tests_dirs]
            for filename in files:
                if filename.endswith(".py"):
                    yield os.path.join(root, filename)
    else:
        yield str(relative_path)
    os.chdir(original)


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


hammett_prefix = "python -m hammett "
