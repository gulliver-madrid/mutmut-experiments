# -*- coding: utf-8 -*-
from copy import copy as copy_obj
from io import open
from pathlib import Path
from typing import Mapping, Sequence, TypedDict

from src.config import Config
from src.context import Context, RelativeMutationID
from src.progress import Progress
from src.shared import FilenameStr
from src.status import UNTESTED, StatusResultStr
from src.storage import storage

from .constants import NUMBER_OF_PROCESSES_IN_PARALLELIZATION_MODE
from .types import MutantQueue

MutationsByFileReadOnly = Mapping[FilenameStr, Sequence[RelativeMutationID]]


class QueueMutants(TypedDict):
    progress: Progress
    config: Config
    mutants_queue: MutantQueue
    mutations_by_file: MutationsByFileReadOnly
    project: Path | None


def queue_mutants(
    *,
    progress: Progress,
    config: Config,
    mutants_queue: MutantQueue,
    mutations_by_file: MutationsByFileReadOnly,
    project: Path | None = None,
) -> None:
    from src.cache.cache import get_cached_mutation_statuses

    storage.project_path.set_project_path(project)

    try:
        index = 0
        for filename, mutations in mutations_by_file.items():
            cached_mutation_statuses = get_cached_mutation_statuses(
                filename, mutations, config.hash_of_tests
            )
            source = get_source(filename)
            for mutation_id in mutations:
                cached_status = cached_mutation_statuses.get(mutation_id)
                assert isinstance(cached_status, str)
                if is_tested(cached_status):
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
        for _ in range(NUMBER_OF_PROCESSES_IN_PARALLELIZATION_MODE):
            mutants_queue.put(("end", None))


def get_source(filename: FilenameStr) -> str:
    with open(storage.project_path.get_current_project_path() / filename) as f:
        source = f.read()
    return source


def is_tested(status: StatusResultStr) -> bool:
    return status != UNTESTED
