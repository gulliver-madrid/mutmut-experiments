# -*- coding: utf-8 -*-
import multiprocessing
from pathlib import Path
from time import time
from typing import Any, Literal, TypeAlias

from src.context import Context, RelativeMutationID
from src.dynamic_config_storage import user_dynamic_config_storage
from src.project import project_path_storage, temp_dir_storage
from src.setup_logging import configure_logger
from src.shared import FilenameStr
from src.status import StatusResultStr
from src.utils import copy_directory

from .run_mutation import run_mutation
from .test_runner import StrConsumer

logger = configure_logger(__name__)


MutantQueueItem: TypeAlias = (
    tuple[Literal["mutant"], Context] | tuple[Literal["end"], None]
)
MutantQueue: TypeAlias = "multiprocessing.Queue[MutantQueueItem]"

ProcessId = int
ResultQueueItem: TypeAlias = (
    tuple[
        Literal["status"], None, StatusResultStr, FilenameStr | None, RelativeMutationID
    ]
    | tuple[Literal["progress"], None, str, None, None]
    | tuple[Literal["end"], ProcessId, None, None, None]
    | tuple[Literal["cycle"], ProcessId, None, None, None]
)
ResultQueue: TypeAlias = "multiprocessing.Queue[ResultQueueItem]"


# check_mutants() se llama en su propio contexto, por lo que hay que prestar atencion a la correcta inicializacion de las variables globales
def check_mutants(
    mutants_queue: MutantQueue,
    results_queue: ResultQueue,
    cycle_process_after: int,
    *,
    process_id: int = 0,
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
    user_dynamic_config_storage.clear_dynamic_config_cache()

    def feedback(line: str) -> None:
        results_queue.put(("progress", None, line, None, None))

    if tmpdirname and temp_dir_storage.tmpdirname is None:
        temp_dir_storage.tmpdirname = tmpdirname

    assert project_path is not None
    project_path_storage.set_project_path(project_path)

    if parallelize:
        assert temp_dir_storage.tmpdirname
        mutation_project_path = Path(temp_dir_storage.tmpdirname)
    else:
        mutation_project_path = project_path_storage.get_current_project_path()

    did_cycle = False

    try:

        count = 0

        while True:
            command, context = mutants_queue.get()
            if command == "end":
                break

            assert context

            if parallelize:
                cluster_module = process_id
                subdir = Path(str(cluster_module))
                current_mutation_project_path = mutation_project_path / subdir

                if not current_mutation_project_path.exists():
                    current_mutation_project_path.mkdir()
                    print(time())
                    copy_directory(
                        str(mutation_project_path),
                        str(current_mutation_project_path),
                    )
                    print(time())
                    print("Directorio copiado")

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
