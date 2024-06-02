# -*- coding: utf-8 -*-
import multiprocessing
from copy import copy as copy_obj
from io import open
from multiprocessing.context import SpawnProcess
from threading import Thread
from typing import Any, Final, cast

from src.cache.cache import MutationsByFile
from src.config import Config
from src.context import Context
from src.mutation_test_runner.check import MutantQueue, ResultQueue, check_mutants
from src.progress import Progress
from src.project import ProjectPath, project_path_storage, temp_dir_storage
from src.status import UNTESTED, StatusResultStr


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

        results_queue: ResultQueue = mp_ctx.Queue(maxsize=100)

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
                    tmpdirname=temp_dir_storage.tmpdirname,
                    project_path=project_path
                    or project_path_storage.get_current_project_path(),
                    parallelize=config.parallelize,
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
