# -*- coding: utf-8 -*-
import multiprocessing
import os
from pathlib import Path
import shlex
import subprocess
import sys
from io import open, TextIOBase
from shutil import move, copy
from time import time
from typing import (
    Callable,
    Final,
    Literal,
    Tuple,
    TypeAlias,
)

from src.config import Config
from src.context import Context, RelativeMutationID
from src.dir_context import DirContext
from src.dynamic_config_storage import user_dynamic_config_storage
from src.mutate import mutate_from_context
from src.process import popen_streaming_output
from src.project import ProjectPath, project_path_storage, temp_dir_storage
from src.mutations import SkipException
from src.shared import FilenameStr
from src.status import (
    BAD_SURVIVED,
    BAD_TIMEOUT,
    OK_KILLED,
    OK_SUSPICIOUS,
    SKIPPED,
    UNTESTED,
    StatusResultStr,
)

StrConsumer = Callable[[str], None]

MutantQueueItem: TypeAlias = (
    tuple[Literal["mutant"], Context] | tuple[Literal["end"], None]
)
MutantQueue: TypeAlias = "multiprocessing.Queue[MutantQueueItem]"


ResultQueueItem: TypeAlias = (
    tuple[Literal["status"], StatusResultStr, FilenameStr | None, RelativeMutationID]
    | tuple[Literal["progress"], str, None, None]
    | tuple[Literal["end", "cycle"], None, None, None]
)
ResultQueue: TypeAlias = "multiprocessing.Queue[ResultQueueItem]"

hammett_prefix: Final = "python -m hammett "


def mutate_file(backup: bool, context: Context) -> Tuple[str, str]:
    assert isinstance(context.filename, str)
    # directory to apply mutations
    mutation_project_path = Path(
        temp_dir_storage.tmpdirname or project_path_storage.get_current_project_path()
    )
    with open(mutation_project_path / context.filename) as f:
        original = f.read()
    if backup:
        backup_path = mutation_project_path / (context.filename + ".bak")
        # print(f"{backup_path=}")
        with open(backup_path, "w") as f:
            f.write(original)
    mutated, _ = mutate_from_context(context)
    with open(mutation_project_path / context.filename, "w") as f:
        f.write(mutated)
    return original, mutated


def check_mutants(
    mutants_queue: MutantQueue,
    results_queue: ResultQueue,
    cycle_process_after: int,
    *,
    tmpdirname: str | None = None,
    project_path: ProjectPath | None = None,
) -> None:
    assert isinstance(cycle_process_after, int)

    # We want be sure than when mutation tests get called, the dynamic config is obtained again.
    # If not, executing tests after the dynamic config is set could prevent to get a new dynamic config.
    # if directory has changed.
    # This is probably not really needed in the regular program flow (that uses spawn).
    # More info: https://stackoverflow.com/questions/64095876/multiprocessing-fork-vs-spawn
    user_dynamic_config_storage.clear_dynamic_config_cache()

    def feedback(line: str) -> None:
        results_queue.put(("progress", line, None, None))

    if tmpdirname and temp_dir_storage.tmpdirname is None:
        temp_dir_storage.tmpdirname = tmpdirname

    did_cycle = False

    try:
        count = 0
        while True:
            command, context = mutants_queue.get()
            if command == "end":
                break

            assert context

            # assert temp_dir_storage.tmpdirname  # TODO: remove! debug!
            status = run_mutation(
                context,
                feedback,
                project_path=project_path,
            )
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
    context: Context,
    callback: StrConsumer,
    project_path: ProjectPath | None = None,
) -> StatusResultStr:
    """
    :return: (computed or cached) status of the tested mutant, one of mutant_statuses
    """
    from src.cache.cache import cached_mutation_status

    assert context.config is not None
    assert context.filename is not None
    if project_path is not None:
        project_path_storage.set_project_path(project_path)
    # TODO: intentar pasar esta logica a check_mutants()
    mutation_project_path = (
        temp_dir_storage.tmpdirname or project_path_storage.get_current_project_path()
    )
    # print(f"{mutation_project_path=}")

    with DirContext(mutation_project_path):

        dynamic_config = user_dynamic_config_storage.get_dynamic_config()
        cached_status = cached_mutation_status(
            context.filename, context.mutation_id, context.config.hash_of_tests
        )

        if cached_status != UNTESTED and context.config.total != 1:
            return cached_status

        config = context.config
        if dynamic_config is not None and hasattr(dynamic_config, "pre_mutation"):
            context.current_line_index = context.mutation_id.line_number
            try:
                dynamic_config.pre_mutation(context=context)
            except SkipException:
                return SKIPPED
            if context.skip:
                return SKIPPED

        if config.pre_mutation:
            result = (
                subprocess.check_output(config.pre_mutation, shell=True)
                .decode()
                .strip()
            )
            if result and not config.swallow_output:
                callback(result)

        try:
            mutate_file(backup=True, context=context)
            start = time()
            try:
                survived = _tests_pass(config=config, callback=callback)
                if (
                    survived
                    and config.test_command != config.default_test_command
                    and config.rerun_all
                ):
                    # rerun the whole test suite to be sure the mutant can not be killed by other tests
                    config.test_command = config.default_test_command
                    survived = _tests_pass(config=config, callback=callback)
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

            move(context.filename + ".bak", context.filename)

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


def _tests_pass(config: Config, callback: StrConsumer) -> bool:
    """
    :return: :obj:`True` if the tests pass, otherwise :obj:`False`
    """
    if config.using_testmon:
        copy(".testmondata-initial", ".testmondata")

    use_special_case = True

    # Special case for hammett! We can do in-process test running which is much faster
    if use_special_case and config.test_command.startswith(hammett_prefix):
        return _hammett_tests_pass(config, callback)

    returncode = popen_streaming_output(
        config.test_command, callback, timeout=config.baseline_time_elapsed * 10
    )
    return returncode != 1


def _hammett_tests_pass(config: Config, callback: StrConsumer) -> bool:
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
