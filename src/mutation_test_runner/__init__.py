# -*- coding: utf-8 -*-
import multiprocessing
import os
import shlex
import subprocess
import sys
from copy import copy as copy_obj
from io import open, TextIOBase
from multiprocessing.context import SpawnProcess
from shutil import move, copy
from threading import Thread
from time import time
from typing import (
    Any,
    Callable,
    Final,
    Literal,
    Tuple,
    TypeAlias,
)


from src.cache.cache import MutationsByFile
from src.config import Config
from src.context import Context, RelativeMutationID
from src.dynamic_config_storage import user_dynamic_config_storage
from src.mutate import mutate_from_context
from src.process import popen_streaming_output
from src.progress import Progress
from src.project import ProjectPath, project_path_storage
from src.mutations import SkipException
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
    tuple[Literal["status"], str, str | None, RelativeMutationID]
    | tuple[Literal["progress"], str, None, None]
    | tuple[Literal["end", "cycle"], None, None, None]
)
ResultQueue: TypeAlias = "multiprocessing.Queue[ResultQueueItem]"

hammett_prefix: Final = "python -m hammett "


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


CYCLE_PROCESS_AFTER: Final = 100


def queue_mutants(
    *,
    progress: Progress,
    config: Config,
    mutants_queue: MutantQueue,
    mutations_by_file: MutationsByFile,
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


def check_mutants(
    mutants_queue: MutantQueue,
    results_queue: ResultQueue,
    cycle_process_after: int,
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


class MutationTestsRunner:
    def __init__(self) -> None:
        # List of active multiprocessing queues
        self._active_queues: list["multiprocessing.Queue[Any]"] = []

    def run_mutation_tests(
        self,
        config: Config,
        progress: Progress,
        mutations_by_file: MutationsByFile | None,
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
