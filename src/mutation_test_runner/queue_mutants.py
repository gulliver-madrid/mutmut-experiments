# -*- coding: utf-8 -*-
from copy import copy as copy_obj
from dataclasses import dataclass
from io import open
from pathlib import Path
from typing import Iterator, Literal, Mapping, Sequence, TypedDict

from src.cache.cache import get_cached_mutation_statuses
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

    storage.project_path.set_project_path(project)

    try:
        for mutant in _get_mutants_by_testing_status(mutations_by_file, config):
            if mutant.tested:
                progress.register(mutant.cached_status)  # pyright: ignore
            else:
                mutants_queue.put(("mutant", mutant.context))  # pyright: ignore

    finally:
        for _ in range(NUMBER_OF_PROCESSES_IN_PARALLELIZATION_MODE):
            mutants_queue.put(("end", None))


@dataclass
class Tested:
    cached_status: StatusResultStr
    tested: Literal[True] = True


@dataclass
class Untested:
    context: Context
    tested: Literal[False] = False


def _get_mutants_by_testing_status(
    mutations_by_file: MutationsByFileReadOnly, config: Config
) -> Iterator[Tested | Untested]:
    index = 0
    for filename, mutations in mutations_by_file.items():
        cached_mutation_statuses = get_cached_mutation_statuses(
            filename, mutations, config.hash_of_tests
        )
        source = get_source(filename)
        for mutation_id in mutations:
            cached_status = cached_mutation_statuses.get(mutation_id)
            if cached_status is None:
                raise RuntimeError(f"Cached status not found for {mutation_id}")

            if _is_tested(cached_status):
                yield Tested(cached_status)
                continue

            context = Context(
                mutation_id=mutation_id,
                filename=filename,
                dict_synonyms=config.dict_synonyms,
                config=copy_obj(config),
                source=source,
                index=index,
            )
            yield Untested(context)
            index += 1


def get_source(filename: FilenameStr) -> str:
    with open(storage.project_path.get_current_project_path() / filename) as f:
        source = f.read()
    return source


def _is_tested(status: StatusResultStr) -> bool:
    return status != UNTESTED
