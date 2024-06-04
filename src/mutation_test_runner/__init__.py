# -*- coding: utf-8 -*-
import multiprocessing
from multiprocessing.context import SpawnProcess
from pathlib import Path
from threading import Thread
from typing import Any, Final, cast

from src.cache.cache import MutationsByFile
from src.config import Config
from src.progress import Progress
from src.status import StatusResultStr
from src.storage import storage
from src.utils import copy_directory

from .check import CheckMutantsKwargs, check_mutants
from .constants import (
    CYCLE_PROCESS_AFTER,
    NUMBER_OF_PROCESSES_IN_PARALLELIZATION_MODE,
)
from .queue_mutants import QueueMutants, queue_mutants
from .types import ProcessId, ResultQueue


class MutationTestsRunner:
    def __init__(self) -> None:
        # List of active multiprocessing queues
        self._active_queues: list["multiprocessing.Queue[Any]"] = []

    def run_mutation_tests(
        self,
        config: Config,
        progress: Progress,
        mutations_by_file: MutationsByFile,
    ) -> None:
        from src.cache.cache import update_mutant_status

        assert mutations_by_file is not None

        process_id: int | None = None

        if config.parallelize:
            assert storage.temp_dir.tmpdirname
            mutation_project_path = Path(storage.temp_dir.tmpdirname)
            copied = False
            for process_id in range(NUMBER_OF_PROCESSES_IN_PARALLELIZATION_MODE):
                subdir = Path(str(process_id))
                current_mutation_project_path = mutation_project_path / subdir

                if not current_mutation_project_path.exists():
                    current_mutation_project_path.mkdir()
                    copy_directory(
                        str(mutation_project_path),
                        str(current_mutation_project_path),
                    )
                    copied = True
            if copied:
                print("Directorios copiados")

        # Need to explicitly use the spawn method for python < 3.8 on macOS
        mp_ctx = multiprocessing.get_context("spawn")

        mutants_queue = mp_ctx.Queue(maxsize=100)
        self.add_to_active_queues(mutants_queue)

        queue_mutants_thread = Thread(
            target=queue_mutants,
            name="queue_mutants",
            daemon=True,
            kwargs=QueueMutants(
                progress=progress,
                config=config,
                mutants_queue=mutants_queue,
                mutations_by_file=mutations_by_file,
                project=storage.project_path.get_current_project_path(),
            ),
        )

        queue_mutants_thread.start()

        results_queue: ResultQueue = mp_ctx.Queue(maxsize=100)

        self.add_to_active_queues(results_queue)

        def create_worker(process_id: ProcessId = ProcessId(0)) -> SpawnProcess:
            t = mp_ctx.Process(
                target=check_mutants,
                name="check_mutants",
                daemon=True,
                kwargs=CheckMutantsKwargs(
                    mutants_queue=mutants_queue,
                    results_queue=results_queue,
                    cycle_process_after=CYCLE_PROCESS_AFTER,
                    tmpdirname=storage.temp_dir.tmpdirname,
                    project_path=storage.project_path.get_current_project_path(),
                    parallelize=config.parallelize,
                    process_id=process_id,
                ),
            )
            t.start()
            return t

        number_of_processes: Final = (
            NUMBER_OF_PROCESSES_IN_PARALLELIZATION_MODE if config.parallelize else 1
        )
        check_mutant_processes = {
            i: create_worker(ProcessId(i)) for i in range(number_of_processes)
        }
        finished: dict[int, SpawnProcess] = {}

        while True:
            command, process_id, status, filename, mutation_id = results_queue.get()
            if command == "end":
                assert process_id is not None
                finished[process_id] = check_mutant_processes[process_id]
                del check_mutant_processes[process_id]
                if not check_mutant_processes:
                    for process in finished.values():
                        process.join()
                    break

            elif command == "cycle":
                assert process_id is not None
                check_mutant_processes[process_id] = create_worker()

            elif command == "progress":
                if not config.swallow_output:
                    print(status, end="", flush=True)
                elif not config.no_progress:
                    progress.print()

            else:
                assert command == "status"

                status = cast(StatusResultStr, status)

                progress.register(status)

                assert mutation_id is not None

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
