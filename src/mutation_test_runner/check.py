# -*- coding: utf-8 -*-
from pathlib import Path
from typing import Any, TypedDict

from src.context import Context
from src.tools import configure_logger
from src.storage import storage

from .run_mutation import run_mutation
from .test_runner import StrConsumer
from .types import MutantQueue, ProcessId, ResultQueue

logger = configure_logger(__name__)


class CheckMutantsKwargs(TypedDict):
    mutants_queue: MutantQueue
    results_queue: ResultQueue
    cycle_process_after: int
    process_id: ProcessId
    tmpdirname: str | None
    project_path: Path
    parallelize: bool


# check_mutants() se llama en su propio contexto, por lo que hay que prestar atencion a la correcta inicializacion de las variables globales
def check_mutants(
    mutants_queue: MutantQueue,
    results_queue: ResultQueue,
    cycle_process_after: int,
    *,
    process_id: ProcessId = ProcessId(0),
    tmpdirname: str | None = None,
    # aqui project_path debe ser la que realmente se espera que sea
    # aunque el usuario no lo haya indicado explicitamente
    project_path: Path,
    parallelize: bool = False,
) -> None:
    assert isinstance(cycle_process_after, int)
    assert project_path is not None

    # We want be sure than when mutation tests get called, the dynamic config is obtained again.
    # If not, executing tests after the dynamic config is set could prevent to get a new dynamic config.
    # if directory has changed.
    # This is probably not really needed in the regular program flow (that uses spawn).
    # More info: https://stackoverflow.com/questions/64095876/multiprocessing-fork-vs-spawn
    storage.dynamic_config.clear_cache()

    def feedback(line: str) -> None:
        results_queue.put(("progress", None, line, None, None))

    assert project_path is not None
    storage.project_path.set_project_path(project_path)

    if parallelize:
        if tmpdirname and storage.temp_dir.tmpdirname is None:
            storage.temp_dir.tmpdirname = tmpdirname
        assert storage.temp_dir.tmpdirname
        mutation_project_path = Path(storage.temp_dir.tmpdirname)
    else:
        mutation_project_path = storage.project_path.get_current_project_path()

    did_cycle = False

    try:

        count = 0

        while True:
            command, context = mutants_queue.get()
            if command == "end":
                break

            assert context

            if parallelize:
                subdir = Path(str(process_id))
                current_mutation_project_path = mutation_project_path / subdir

                assert current_mutation_project_path.exists()

            else:
                current_mutation_project_path = mutation_project_path

            status = run_mutation(
                context,
                feedback,
                mutation_project_path=current_mutation_project_path,
            )
            results_queue.put(
                ("status", None, status, context.filename, context.mutation_id)
            )

            count += 1
            if count == cycle_process_after:
                results_queue.put(("cycle", process_id, None, None, None))
                did_cycle = True
                break

    finally:

        if not did_cycle:
            results_queue.put(("end", process_id, None, None, None))


# TODO: remove unused function
def process_mutant(
    context: Context,
    feedback: StrConsumer,
    current_mutation_project_path: Path,
    results_queue: Any,
) -> None:
    status = run_mutation(
        context, feedback, mutation_project_path=current_mutation_project_path
    )
    results_queue.put(("status", status, context.filename, context.mutation_id))
