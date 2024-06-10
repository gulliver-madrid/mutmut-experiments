# -*- coding: utf-8 -*-

import os
from difflib import unified_diff
from io import open
from types import NoneType
from typing import (
    TYPE_CHECKING,
    Dict,
    List,
    Sequence,
    Tuple,
)

from pony.orm import select

from src.context import Context, RelativeMutationID
from src.mutate import mutate_from_context
from src.tools import configure_logger
from src.shared import NO_TESTS_FOUND, FilenameStr, HashResult
from src.status import OK_KILLED, UNTESTED, StatusResultStr
from src.storage import storage
from src.utils import SequenceStr, split_lines

from .db_core import db_session, init_db
from .hash import hash_of
from .model import (
    Line,
    MiscData,
    Mutant,
    SourceFile,
    get_mutant,
    get_mutants,
    get_or_create,
)
from .update_line_numbers import update_line_numbers

MutationsByFile = Dict[FilenameStr, List[RelativeMutationID]]

if TYPE_CHECKING:
    from pony.orm import Query

logger = configure_logger(__name__)


def get_unified_diff(
    pk: int | str,
    dict_synonyms: SequenceStr,
    update_cache: bool = True,
    source: str | None = None,
) -> str:
    assert isinstance(pk, (int, str))
    assert isinstance(update_cache, bool)
    filename, mutation_id = filename_and_mutation_id_from_pk(pk)
    if source is None:
        with open(storage.project_path.get_current_project_path() / filename) as f:
            source = f.read()

    return get_unified_diff_from_filename_and_mutation_id(
        source, filename, mutation_id, dict_synonyms, update_cache
    )


def get_unified_diff_from_filename_and_mutation_id(
    source: str | None,
    filename: FilenameStr,
    mutation_id: RelativeMutationID,
    dict_synonyms: SequenceStr,
    update_cache: bool,
) -> str:
    assert isinstance(source, (str, NoneType))

    if update_cache:
        update_line_numbers(filename)

    if source is None:
        with open(filename) as f:
            source = f.read()
    context = Context(
        source=source,
        filename=filename,
        mutation_id=mutation_id,
        dict_synonyms=dict_synonyms,
    )
    mutated_source, number_of_mutations_performed = mutate_from_context(context)
    if not number_of_mutations_performed:
        return ""

    output = ""
    for line in unified_diff(
        split_lines(source),
        split_lines(mutated_source),
        fromfile=filename,
        tofile=filename,
        lineterm="",
    ):
        output += line + "\n"
    return output


@init_db
@db_session
def register_mutants(mutations_by_file: MutationsByFile) -> None:
    for filename, mutation_ids in mutations_by_file.items():
        hash = hash_of(filename)
        sourcefile = get_or_create(SourceFile, filename=filename)
        if hash == sourcefile.hash:
            continue

        for mutation_id in mutation_ids:
            line = _get_line(sourcefile, mutation_id)
            if line is None:
                raise ValueError(
                    "Obtained null line for mutation_id: {}".format(mutation_id)
                )
            get_or_create(
                Mutant,
                line=line,
                index=mutation_id.index,
                defaults=dict(status=UNTESTED),
            )

        sourcefile.hash = hash


@init_db
@db_session
def update_mutant_status(
    file_to_mutate: FilenameStr | None,
    mutation_id: RelativeMutationID,
    status: StatusResultStr,
    tests_hash: HashResult,
) -> None:
    sourcefile = SourceFile.get(filename=file_to_mutate)
    line = _get_line(sourcefile, mutation_id)
    assert line
    mutant = get_mutant(line=line, index=mutation_id.index)
    assert mutant
    mutant.status = status
    mutant.tested_against_hash = tests_hash


@init_db
@db_session
def get_cached_mutation_statuses(
    filename: FilenameStr,
    mutations: Sequence[RelativeMutationID],
    hash_of_tests: HashResult,
) -> dict[RelativeMutationID, StatusResultStr]:
    sourcefile = SourceFile.get(filename=filename)
    assert sourcefile

    line_obj_by_line: dict[str, Line] = {}

    result: dict[RelativeMutationID, StatusResultStr] = {}

    for mutation_id in mutations:
        if mutation_id.line not in line_obj_by_line:
            line_from_db = _get_line(sourcefile, mutation_id)
            assert line_from_db is not None
            line_obj_by_line[mutation_id.line] = line_from_db
        line = line_obj_by_line[mutation_id.line]
        assert line
        mutant = get_mutant(line=line, index=mutation_id.index)
        if mutant is None:
            mutant = get_or_create(
                Mutant,
                line=line,
                index=mutation_id.index,
                defaults=dict(status=UNTESTED),
            )

        result[mutation_id] = _get_mutant_result(mutant, hash_of_tests)

    return result


@init_db
@db_session
def cached_mutation_status(
    filename: FilenameStr,
    mutation_id: RelativeMutationID,
    hash_of_tests: HashResult,
) -> StatusResultStr:
    assert isinstance(filename, str)  # guess
    assert isinstance(hash_of_tests, str)  # guess
    sourcefile = SourceFile.get(filename=filename)
    if not sourcefile:
        print(f"{filename=}")
        print(f"{sourcefile=}")
        print(f"{os.getcwd()=}")

    assert sourcefile
    line = _get_line(sourcefile, mutation_id)
    assert line
    mutant = get_mutant(line=line, index=mutation_id.index)
    if mutant is None:
        mutant = get_or_create(
            Mutant, line=line, index=mutation_id.index, defaults=dict(status=UNTESTED)
        )
    return _get_mutant_result(mutant, hash_of_tests)


@init_db
@db_session
def filename_and_mutation_id_from_pk(
    pk: int | str,
) -> Tuple[FilenameStr, RelativeMutationID]:
    if not isinstance(pk, (int, str)):  # pyright: ignore [reportUnnecessaryIsInstance]
        raise ValueError("filename_and_mutation_id_from_pk:", type(pk))
    mutant = get_mutant(id=pk)
    if mutant is None:
        raise ValueError("Obtained null mutant for pk: {}".format(pk))
    return mutant.line.sourcefile.filename, _mutation_id_from_pk(pk)


@init_db
@db_session
def select_mutants_by_status(
    status: StatusResultStr | Sequence[StatusResultStr],
) -> "Query[Mutant, Mutant]":
    if isinstance(status, str):
        status = (status,)
    return select(x for x in get_mutants() if x.status in status)


@init_db
@db_session
def cached_test_time() -> float | None:
    d = MiscData.get(key="baseline_time_elapsed")
    if d:
        assert d.value is not None
        return float(d.value)
    return None


@init_db
@db_session
def set_cached_test_time(
    baseline_time_elapsed: float, current_hash_of_tests: str
) -> None:
    get_or_create(MiscData, key="baseline_time_elapsed").value = str(
        baseline_time_elapsed
    )
    get_or_create(MiscData, key="hash_of_tests").value = current_hash_of_tests


@init_db
@db_session
def cached_hash_of_tests() -> str | None:
    d = MiscData.get(key="hash_of_tests")
    return d.value if d else None


def _get_line(
    sourcefile: SourceFile | None, mutation_id: RelativeMutationID
) -> Line | None:
    return Line.get(
        sourcefile=sourcefile,
        line=mutation_id.line,
        line_number=mutation_id.line_number,
    )


def _get_mutant_result(mutant: Mutant, hash_of_tests: HashResult) -> StatusResultStr:
    if mutant.status == OK_KILLED:
        # We assume that if a mutant was killed, a change to the test
        # suite will mean it's still killed
        return OK_KILLED

    if _mutant_not_currently_tested(mutant, hash_of_tests):
        return UNTESTED

    return mutant.status


def _mutant_not_currently_tested(mutant: Mutant, hash_of_tests: HashResult) -> bool:
    return (
        mutant.tested_against_hash != hash_of_tests
        or mutant.tested_against_hash == NO_TESTS_FOUND
        or hash_of_tests == NO_TESTS_FOUND
    )


@init_db
@db_session
def _mutation_id_from_pk(pk: int | str) -> RelativeMutationID:
    if not isinstance(pk, (int, str)):  # pyright: ignore [reportUnnecessaryIsInstance]
        raise ValueError("mutation_id_from_pk:", type(pk))
    mutant = get_mutant(id=pk)
    assert mutant, dict(id=pk)
    assert isinstance(mutant.line.line, str)  # always true?
    return RelativeMutationID(
        line=mutant.line.line, index=mutant.index, line_number=mutant.line.line_number
    )
