# -*- coding: utf-8 -*-


import hashlib
import os
from difflib import SequenceMatcher, unified_diff
from functools import wraps
from io import open
from itertools import zip_longest
from pathlib import Path
from types import NoneType
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    ContextManager,
    Dict,
    Iterator,
    List,
    Sequence,
    Tuple,
    TypeVar,
)

from pony.orm import select, RowNotFound, ERDiagramError, OperationalError
from typing_extensions import ParamSpec

from src.cache.model import (
    NO_TESTS_FOUND,
    HashStr,
    Line,
    MiscData,
    Mutant,
    NoTestFoundSentinel,
    SourceFile,
    db,
    get_mutant,
    get_mutants,
    get_or_create,
)
from src.context import Context, RelativeMutationID
from src.mutate import mutate_from_context
from src.project import project_path_storage
from src.setup_logging import configure_logger
from src.shared import FilenameStr
from src.status import OK_KILLED, UNTESTED, StatusResultStr
from src.utils import split_lines

MutationsByFile = Dict[FilenameStr, List[RelativeMutationID]]

if TYPE_CHECKING:
    from pony.orm import Query

logger = configure_logger(__name__)

current_db_version = 4


# Used for db_session and init_db
P = ParamSpec("P")
T = TypeVar("T")

if TYPE_CHECKING:

    def db_session(f: Callable[P, T]) -> Callable[P, T]: ...

    db_session_ctx_manager: ContextManager[Any]
else:
    from pony.orm import db_session

    db_session_ctx_manager = db_session


def get_cache_path() -> Path:
    cache_path = _get_cache_path()
    # print(f"{cache_path=}")
    return cache_path


def _get_cache_path() -> Path:
    return project_path_storage.get_current_project_path() / ".mutmut-cache"


def init_db(f: Callable[P, T]) -> Callable[P, T]:
    @wraps(f)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
        if db.provider is None:
            cache_path = get_cache_path()
            logger.info(
                f"El directorio donde se guarda la .mutmut-cache es {project_path_storage.get_current_project_path()}"
            )
            db.bind(provider="sqlite", filename=str(cache_path), create_db=True)

            try:
                db.generate_mapping(create_tables=True)
            except OperationalError:
                pass

            if cache_path.exists():
                # If the existing cache file is out of date, delete it and start over
                with db_session_ctx_manager:  # pyright: ignore
                    try:
                        v = MiscData.get(key="version")
                        if v is None:
                            existing_db_version = 1
                        else:
                            assert v.value is not None
                            existing_db_version = int(v.value)
                    except (RowNotFound, ERDiagramError, OperationalError):
                        existing_db_version = 1

                if existing_db_version != current_db_version:
                    print("mutmut cache is out of date, clearing it...")
                    db.drop_all_tables(with_all_data=True)
                    db.schema = (
                        None  # Pony otherwise thinks we've already created the tables
                    )
                    db.generate_mapping(create_tables=True)

            with db_session_ctx_manager:  # pyright: ignore
                v = get_or_create(MiscData, key="version")
                v.value = str(current_db_version)

        return f(*args, **kwargs)

    return wrapper


def hash_of(filename: FilenameStr) -> HashStr:
    with open(project_path_storage.get_current_project_path() / filename, "rb") as f:
        m = hashlib.sha256()
        m.update(f.read())
        return HashStr(m.hexdigest())


def hash_of_tests(tests_dirs: list[str]) -> HashStr | NoTestFoundSentinel:
    assert isinstance(tests_dirs, list)
    m = hashlib.sha256()
    found_something = False
    for tests_dir in tests_dirs:
        for root, _dirs, files in os.walk(tests_dir):
            for filename in files:
                if not filename.endswith(".py"):
                    continue
                if (
                    not filename.startswith("test")
                    and not filename.endswith("_tests.py")
                    and "test" not in root
                ):
                    continue
                with open(os.path.join(root, filename), "rb") as f:
                    m.update(f.read())
                    found_something = True
    if not found_something:
        return NO_TESTS_FOUND
    return HashStr(m.hexdigest())


def get_unified_diff(
    pk: int | str,
    dict_synonyms: list[str],
    update_cache: bool = True,
    source: str | None = None,
) -> str:
    assert isinstance(pk, (int, str))
    assert isinstance(update_cache, bool)
    assert isinstance(dict_synonyms, list)
    filename, mutation_id = filename_and_mutation_id_from_pk(pk)
    if source is None:
        with open(project_path_storage.get_current_project_path() / filename) as f:
            source = f.read()

    return get_unified_diff_from_filename_and_mutation_id(
        source, filename, mutation_id, dict_synonyms, update_cache
    )


def get_unified_diff_from_filename_and_mutation_id(
    source: str | None,
    filename: FilenameStr,
    mutation_id: RelativeMutationID,
    dict_synonyms: list[str],
    update_cache: bool,
) -> str:
    assert isinstance(dict_synonyms, list)
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


def sequence_ops(
    a: list[str], b: list[str]
) -> Iterator[tuple[str, str, int | None, str | None, int | None]]:
    sequence_matcher = SequenceMatcher(a=a, b=b)

    for tag, i1, i2, j1, j2 in sequence_matcher.get_opcodes():
        a_sub_sequence = a[i1:i2]
        b_sub_sequence = b[j1:j2]
        for x in zip_longest(
            a_sub_sequence, range(i1, i2), b_sub_sequence, range(j1, j2)
        ):
            yield (tag,) + x


@init_db
@db_session
def update_line_numbers(filename: FilenameStr) -> None:
    hash = hash_of(filename)
    sourcefile = get_or_create(SourceFile, filename=filename)
    if hash == sourcefile.hash:
        return
    cached_line_objects = list(sourcefile.lines.order_by(Line.line_number))

    cached_lines = [x.line for x in cached_line_objects if x.line is not None]
    assert len(cached_line_objects) == len(cached_lines)

    with open(filename) as f:
        existing_lines = [x.strip("\n") for x in f.readlines()]

    if not cached_lines:
        for i, line in enumerate(existing_lines):
            Line(sourcefile=sourcefile, line=line, line_number=i)
        return

    for command, _a, a_index, b, b_index in sequence_ops(cached_lines, existing_lines):
        if command == "equal":
            assert isinstance(a_index, int)
            assert isinstance(b_index, int)
            if a_index != b_index:
                cached_obj = cached_line_objects[a_index]
                assert cached_obj.line == existing_lines[b_index]
                cached_obj.line_number = b_index

        elif command == "delete":
            assert isinstance(a_index, int)
            cached_line_objects[a_index].delete()

        elif command == "insert":
            if b is not None:
                assert isinstance(b_index, int)
                Line(sourcefile=sourcefile, line=b, line_number=b_index)

        elif command == "replace":
            if a_index is not None:
                cached_line_objects[a_index].delete()
            if b is not None:
                assert isinstance(b_index, int)
                Line(sourcefile=sourcefile, line=b, line_number=b_index)

        else:
            raise ValueError("Unknown opcode from SequenceMatcher: {}".format(command))

    sourcefile.hash = hash


@init_db
@db_session
def register_mutants(mutations_by_file: MutationsByFile) -> None:
    for filename, mutation_ids in mutations_by_file.items():
        hash = hash_of(filename)
        sourcefile = get_or_create(SourceFile, filename=filename)
        if hash == sourcefile.hash:
            continue

        for mutation_id in mutation_ids:
            line = Line.get(
                sourcefile=sourcefile,
                line=mutation_id.line,
                line_number=mutation_id.line_number,
            )
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
    file_to_mutate: str,
    mutation_id: RelativeMutationID,
    status: StatusResultStr,
    tests_hash: HashStr | NoTestFoundSentinel,
) -> None:
    sourcefile = SourceFile.get(filename=file_to_mutate)
    line = Line.get(
        sourcefile=sourcefile,
        line=mutation_id.line,
        line_number=mutation_id.line_number,
    )
    assert line
    mutant = get_mutant(line=line, index=mutation_id.index)
    assert mutant
    mutant.status = status
    mutant.tested_against_hash = tests_hash


@init_db
@db_session
def get_cached_mutation_statuses(
    filename: FilenameStr,
    mutations: List[RelativeMutationID],
    hash_of_tests: HashStr | NoTestFoundSentinel,
) -> dict[RelativeMutationID, StatusResultStr]:
    sourcefile = SourceFile.get(filename=filename)
    assert sourcefile

    line_obj_by_line: dict[str, Line] = {}

    result: dict[RelativeMutationID, StatusResultStr] = {}

    for mutation_id in mutations:
        if mutation_id.line not in line_obj_by_line:
            line_from_db = Line.get(
                sourcefile=sourcefile,
                line=mutation_id.line,
                line_number=mutation_id.line_number,
            )
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

        result[mutation_id] = mutant.status
        if mutant.status == OK_KILLED:
            # We assume that if a mutant was killed, a change to the test
            # suite will mean it's still killed
            result[mutation_id] = mutant.status
        else:
            if (
                mutant.tested_against_hash != hash_of_tests
                or mutant.tested_against_hash == NO_TESTS_FOUND
                or hash_of_tests == NO_TESTS_FOUND
            ):
                result[mutation_id] = UNTESTED
            else:
                result[mutation_id] = mutant.status

    return result


@init_db
@db_session
def cached_mutation_status(
    filename: FilenameStr,
    mutation_id: RelativeMutationID,
    hash_of_tests: HashStr | NoTestFoundSentinel,
) -> StatusResultStr:
    assert isinstance(filename, str)  # guess
    assert isinstance(hash_of_tests, str)  # guess
    sourcefile = SourceFile.get(filename=filename)
    assert sourcefile
    line = Line.get(
        sourcefile=sourcefile,
        line=mutation_id.line,
        line_number=mutation_id.line_number,
    )
    assert line
    mutant = get_mutant(line=line, index=mutation_id.index)
    if mutant is None:
        mutant = get_or_create(
            Mutant, line=line, index=mutation_id.index, defaults=dict(status=UNTESTED)
        )

    if mutant.status == OK_KILLED:
        # We assume that if a mutant was killed, a change to the test
        # suite will mean it's still killed
        return OK_KILLED

    if (
        mutant.tested_against_hash != hash_of_tests
        or mutant.tested_against_hash == NO_TESTS_FOUND
        or hash_of_tests == NO_TESTS_FOUND
    ):
        return UNTESTED

    return mutant.status


@init_db
@db_session
def mutation_id_from_pk(pk: int | str) -> RelativeMutationID:
    if not isinstance(pk, (int, str)):  # pyright: ignore [reportUnnecessaryIsInstance]
        raise ValueError("mutation_id_from_pk:", type(pk))
    mutant = get_mutant(id=pk)
    assert mutant, dict(id=pk)
    assert isinstance(mutant.line.line, str)  # always true?
    return RelativeMutationID(
        line=mutant.line.line, index=mutant.index, line_number=mutant.line.line_number
    )


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
    return mutant.line.sourcefile.filename, mutation_id_from_pk(pk)


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
