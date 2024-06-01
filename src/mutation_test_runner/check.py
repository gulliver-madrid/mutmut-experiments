# -*- coding: utf-8 -*-
import multiprocessing
from pathlib import Path
import subprocess
from io import open
from shutil import move
from time import time
from typing import (
    Literal,
    Tuple,
    TypeAlias,
)

from src.context import Context, RelativeMutationID
from src.dir_context import DirContext
from src.dynamic_config_storage import user_dynamic_config_storage
from src.mutate import mutate_from_context
from src.mutation_test_runner.test_runner import StrConsumer, TestRunner
from src.project import project_path_storage, temp_dir_storage
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


# check_mutants() se llama en su propio contexto, por lo que hay que prestar atencion a la correcta inicializacion de las variables globales
def check_mutants(
    mutants_queue: MutantQueue,
    results_queue: ResultQueue,
    cycle_process_after: int,
    *,
    tmpdirname: str | None = None,
    # aqui project_path debe ser la que realmente se espera que sea
    # aunque el usuario no lo haya indicado explicitamente
    project_path: Path,
) -> None:
    assert isinstance(cycle_process_after, int)
    assert project_path is not None

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

    if project_path is not None:
        project_path_storage.set_project_path(project_path)

    mutation_project_path = Path(
        temp_dir_storage.tmpdirname or project_path_storage.get_current_project_path()
    )

    did_cycle = False

    try:
        count = 0
        while True:
            command, context = mutants_queue.get()
            if command == "end":
                break

            assert context

            status = run_mutation(
                context,
                feedback,
                mutation_project_path=mutation_project_path,
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
    *,
    mutation_project_path: Path,
) -> StatusResultStr:
    """
    :return: (computed or cached) status of the tested mutant, one of mutant_statuses
    """
    from src.cache.cache import cached_mutation_status

    assert context.config is not None
    assert context.filename is not None

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

        test_runner = TestRunner()
        try:
            mutate_file(backup=True, context=context)
            start = time()
            try:
                survived = test_runner.tests_pass(config=config, callback=callback)
                if (
                    survived
                    and config.test_command != config.default_test_command
                    and config.rerun_all
                ):
                    # rerun the whole test suite to be sure the mutant can not be killed by other tests
                    config.test_command = config.default_test_command
                    survived = test_runner.tests_pass(config=config, callback=callback)
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
