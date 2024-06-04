# -*- coding: utf-8 -*-
from copy import copy as copy_obj
from io import open
from typing import Mapping, Sequence

from src.config import Config
from src.context import Context, RelativeMutationID
from src.progress import Progress
from src.shared import FilenameStr
from src.status import UNTESTED
from src.storage import ProjectPath, project_path_storage

from .constants import NUMBER_OF_PROCESSES_IN_PARALLELIZATION_MODE
from .types import MutantQueue

MutationsByFileReadOnly = Mapping[FilenameStr, Sequence[RelativeMutationID]]


def queue_mutants(
    *,
    progress: Progress,
    config: Config,
    mutants_queue: MutantQueue,
    mutations_by_file: MutationsByFileReadOnly,
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
        for _ in range(NUMBER_OF_PROCESSES_IN_PARALLELIZATION_MODE):
            mutants_queue.put(("end", None))
