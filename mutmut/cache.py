# -*- coding: utf-8 -*-


from dataclasses import field
import hashlib
import os
from collections import defaultdict
from difflib import SequenceMatcher, unified_diff
from functools import wraps
from io import open
from itertools import groupby, zip_longest
from os.path import join, dirname
from types import NoneType
from typing import TYPE_CHECKING, Any, Callable, ContextManager, Dict, Iterable, Iterator, List, Mapping, Tuple, Type, TypeAlias, TypeVar, cast, overload
from typing_extensions import ParamSpec

from typing_extensions import Self
from junit_xml import TestSuite, TestCase, to_xml_report_string  # type: ignore [import-untyped]
from pony.orm import Database, Required, Set, Optional, select, \
    PrimaryKey, RowNotFound, ERDiagramError, OperationalError

from mutmut.context import Context, RelativeMutationID
from mutmut.mutate import mutate
from mutmut.utils import ranges
from mutmut.setup_logging import configure_logger
from mutmut.status import BAD_SURVIVED, BAD_TIMEOUT, MUTANT_STATUSES, OK_KILLED, OK_SUSPICIOUS, SKIPPED, UNTESTED, StatusStr


if TYPE_CHECKING:
    from pony.orm import Query


logger = configure_logger(__name__)

HashOfTestsStr: TypeAlias = str

# Used for db_session and init_db
P = ParamSpec('P')
T = TypeVar('T')

if TYPE_CHECKING:
    def db_session(f: Callable[P, T]) -> Callable[P, T]:
        ...

    db_session_ctx_manager: ContextManager[Any]
else:
    from pony.orm import db_session
    db_session_ctx_manager = db_session


db = Database()

# type checking
if TYPE_CHECKING:
    class DbEntity:
        @classmethod
        def get(cls, **kwargs: Any) -> Self | None:
            ...
else:
    DbEntity = db.Entity


current_db_version = 4


NO_TESTS_FOUND = 'NO TESTS FOUND'


class MiscData(DbEntity):
    key = PrimaryKey(str, auto=True)
    value = Optional(str, autostrip=False)


if TYPE_CHECKING:
    class SourceFile(DbEntity):
        filename: str
        hash: str | None
        lines: Set['Line']
else:
    class SourceFile(DbEntity):  # type: ignore [valid-type]
        filename = Required(str, autostrip=False)
        hash = Optional(str)
        lines = Set('Line')


if TYPE_CHECKING:
    class Line(DbEntity):
        sourcefile: SourceFile
        line: str | None
        line_number: int
        mutants: Set['Mutant']

        def __init__(self, *, sourcefile: Any, line: str, line_number: int) -> None:
            ...

        def delete(self) -> None:
            ...
else:
    class Line(DbEntity):  # type: ignore [valid-type]
        sourcefile = Required(SourceFile)
        line = Optional(str, autostrip=False)
        line_number = Required(int)
        mutants = Set('Mutant')


if TYPE_CHECKING:
    from dataclasses import dataclass

    @dataclass
    class Mutant(DbEntity):
        line: Line
        index: int
        status: str
        tested_against_hash: str | None = field(default=None)
        id: int = field(default=0)

else:
    class Mutant(DbEntity):
        line = Required(Line)
        index = Required(int)
        tested_against_hash = Optional(str, autostrip=False)
        status = Required(str, autostrip=False)  # really an enum of mutant_statuses


def get_mutants() -> Iterable[Mutant]:
    return Mutant  # type: ignore [return-value]


@overload
def get_mutant(*, id: int | str) -> Mutant | None:
    ...


@overload
def get_mutant(*, line: Line, index: int) -> Mutant | None:
    ...


def get_mutant(**kwargs: Any) -> Mutant | None:
    return Mutant.get(**kwargs)


def init_db(f: Callable[P, T]) -> Callable[P, T]:
    @wraps(f)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
        if db.provider is None:
            cache_filename = os.path.join(os.getcwd(), '.mutmut-cache')
            db.bind(provider='sqlite', filename=cache_filename, create_db=True)

            try:
                db.generate_mapping(create_tables=True)
            except OperationalError:
                pass

            if os.path.exists(cache_filename):
                # If the existing cache file is out of date, delete it and start over
                with db_session_ctx_manager:  # pyright: ignore
                    try:
                        v = MiscData.get(key='version')
                        if v is None:
                            existing_db_version = 1
                        else:
                            assert v.value is not None
                            existing_db_version = int(v.value)
                    except (RowNotFound, ERDiagramError, OperationalError):
                        existing_db_version = 1

                if existing_db_version != current_db_version:
                    print('mutmut cache is out of date, clearing it...')
                    db.drop_all_tables(with_all_data=True)
                    db.schema = None  # Pony otherwise thinks we've already created the tables
                    db.generate_mapping(create_tables=True)

            with db_session_ctx_manager:  # pyright: ignore
                v = get_or_create(MiscData, key='version')
                v.value = str(current_db_version)

        return f(*args, **kwargs)
    return wrapper


def hash_of(filename: str) -> str:
    with open(filename, 'rb') as f:
        m = hashlib.sha256()
        m.update(f.read())
        return m.hexdigest()


def hash_of_tests(tests_dirs: list[str]) -> str:
    assert isinstance(tests_dirs, list)
    m = hashlib.sha256()
    found_something = False
    for tests_dir in tests_dirs:
        for root, _dirs, files in os.walk(tests_dir):
            for filename in files:
                if not filename.endswith('.py'):
                    continue
                if not filename.startswith('test') and not filename.endswith('_tests.py') and 'test' not in root:
                    continue
                with open(os.path.join(root, filename), 'rb') as f:
                    m.update(f.read())
                    found_something = True
    if not found_something:
        return NO_TESTS_FOUND
    return m.hexdigest()


def get_apply_line(mutant: Mutant) -> str:
    apply_line = 'mutmut apply {}'.format(mutant.id)
    return apply_line


@init_db
@db_session
def print_result_cache(show_diffs: bool = False, dict_synonyms: list[str] = [], only_this_file: str | None = None) -> None:
    # CHECK TYPES START
    assert isinstance(dict_synonyms, list)
    assert isinstance(show_diffs, bool)
    # CHECK TYPES END
    print('To apply a mutant on disk:')
    print('    mutmut apply <id>')
    print('')
    print('To show a mutant:')
    print('    mutmut show <id>')
    print('')

    def print_stuff(title: str, mutant_query: 'Query[Mutant, Mutant]') -> None:
        # CHECK TYPES START
        assert isinstance(title, str)
        # CHECK TYPES END
        mutant_list = sorted(mutant_query, key=lambda x: x.line.sourcefile.filename)
        if mutant_list:
            print('')
            print("{} ({})".format(title, len(mutant_list)))
            for filename, mutants_iterator in groupby(mutant_list, key=lambda x: x.line.sourcefile.filename):
                if only_this_file and filename != only_this_file:
                    continue

                mutants = list(mutants_iterator)
                print('')
                print("---- {} ({}) ----".format(filename, len(mutants)))
                print('')
                if show_diffs:
                    with open(filename) as f:
                        source = f.read()

                    for x in mutants:
                        print('# mutant {}'.format(x.id))
                        print(get_unified_diff(x.id, dict_synonyms, update_cache=False, source=source))
                else:
                    print(ranges([x.id for x in mutants]))

    print_stuff('Timed out ⏰', select(x for x in get_mutants() if x.status == BAD_TIMEOUT))
    print_stuff('Suspicious 🤔', select(x for x in get_mutants() if x.status == OK_SUSPICIOUS))
    print_stuff('Survived 🙁', select(x for x in get_mutants() if x.status == BAD_SURVIVED))
    print_stuff('Untested/skipped', select(x for x in get_mutants() if x.status == UNTESTED or x.status == SKIPPED))


@init_db
@db_session
def print_result_ids_cache(desired_status: StatusStr) -> None:
    status = MUTANT_STATUSES[desired_status]
    mutant_query = select(x for x in get_mutants() if x.status == status)
    print(" ".join(str(mutant.id) for mutant in mutant_query))


def get_unified_diff(pk: int | str, dict_synonyms: list[str], update_cache: bool = True, source: str | None = None) -> str:
    assert isinstance(pk, (int, str))
    assert isinstance(update_cache, bool)
    assert isinstance(dict_synonyms, list)
    filename, mutation_id = filename_and_mutation_id_from_pk(pk)
    if source is None:
        with open(filename) as f:
            source = f.read()

    return _get_unified_diff(source, filename, mutation_id, dict_synonyms, update_cache)


def _get_unified_diff(source: str | None, filename: str, mutation_id: RelativeMutationID, dict_synonyms: list[str], update_cache: bool) -> str:
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
    mutated_source, number_of_mutations_performed = mutate(context)
    if not number_of_mutations_performed:
        return ""

    output = ""
    for line in unified_diff(source.split('\n'), mutated_source.split('\n'), fromfile=filename, tofile=filename, lineterm=''):
        output += line + "\n"
    return output


def print_result_cache_junitxml(dict_synonyms: list[str], suspicious_policy: str, untested_policy: str) -> None:
    assert isinstance(dict_synonyms, list)
    report = create_junitxml_report(dict_synonyms, suspicious_policy, untested_policy)
    assert isinstance(report, str)
    print(report)


@init_db
@db_session
def create_junitxml_report(dict_synonyms: list[str], suspicious_policy: str, untested_policy: str) -> str:
    test_cases: list[TestCase] = []
    mutant_list = list(select(x for x in get_mutants()))
    for filename, mutants in groupby(mutant_list, key=lambda x: x.line.sourcefile.filename):
        for mutant in mutants:
            tc = TestCase("Mutant #{}".format(mutant.id), file=filename, line=mutant.line.line_number + 1, stdout=mutant.line.line)
            if mutant.status == BAD_SURVIVED:
                tc.add_failure_info(message=mutant.status, output=get_unified_diff(mutant.id, dict_synonyms))
            if mutant.status == BAD_TIMEOUT:
                tc.add_error_info(message=mutant.status, error_type="timeout", output=get_unified_diff(mutant.id, dict_synonyms))
            if mutant.status == OK_SUSPICIOUS:
                if suspicious_policy != 'ignore':
                    func = getattr(tc, 'add_{}_info'.format(suspicious_policy))
                    func(message=mutant.status, output=get_unified_diff(mutant.id, dict_synonyms))
            if mutant.status == UNTESTED:
                if untested_policy != 'ignore':
                    func = getattr(tc, 'add_{}_info'.format(untested_policy))
                    func(message=mutant.status, output=get_unified_diff(mutant.id, dict_synonyms))

            test_cases.append(tc)

    ts = TestSuite("mutmut", test_cases)
    report: Any = to_xml_report_string([ts])
    assert isinstance(report, str)
    return report


@init_db
@db_session
def create_html_report(dict_synonyms: list[str], directory: str) -> None:
    mutants = sorted(list(select(x for x in get_mutants())), key=lambda x: x.line.sourcefile.filename)

    os.makedirs(directory, exist_ok=True)

    with open(join(directory, 'index.html'), 'w') as index_file:
        index_file.write('<h1>Mutation testing report</h1>')

        index_file.write('Killed %s out of %s mutants' % (len([x for x in mutants if x.status == OK_KILLED]), len(mutants)))

        index_file.write('<table><thead><tr><th>File</th><th>Total</th><th>Skipped</th><th>Killed</th><th>% killed</th><th>Survived</th></thead>')

        for filename, mutants_it in groupby(mutants, key=lambda x: x.line.sourcefile.filename):
            report_filename = join(directory, filename)

            mutants = list(mutants_it)

            with open(filename) as f:
                source = f.read()

            os.makedirs(dirname(report_filename), exist_ok=True)
            with open(join(report_filename + '.html'), 'w') as f:
                mutants_by_status: dict[str, list[Mutant]] = defaultdict(list)
                for mutant in mutants:
                    mutants_by_status[mutant.status].append(mutant)

                f.write('<html><body>')

                f.write('<h1>%s</h1>' % filename)

                killed = len(mutants_by_status[OK_KILLED])
                f.write('Killed %s out of %s mutants' % (killed, len(mutants)))

                index_file.write('<tr><td><a href="%s.html">%s</a></td><td>%s</td><td>%s</td><td>%s</td><td>%.2f</td><td>%s</td>' % (
                    filename,
                    filename,
                    len(mutants),
                    len(mutants_by_status[SKIPPED]),
                    killed,
                    (killed / len(mutants) * 100),
                    len(mutants_by_status[BAD_SURVIVED]),
                ))

                def print_diffs(status: str) -> None:
                    mutants = mutants_by_status[status]
                    for mutant in sorted(mutants, key=lambda m: m.id):
                        assert isinstance(mutant.line.line, str)  # guess
                        mutation_id = RelativeMutationID(mutant.line.line, mutant.index, mutant.line.line_number)
                        diff = _get_unified_diff(source, filename, mutation_id, dict_synonyms, update_cache=False)
                        f.write('<h3>Mutant %s</h3>' % mutant.id)
                        f.write('<pre>%s</pre>' % diff)

                if mutants_by_status[BAD_TIMEOUT]:
                    f.write('<h2>Timeouts</h2>')
                    f.write('Mutants that made the test suite take a lot longer so the tests were killed.')
                    print_diffs(BAD_TIMEOUT)

                if mutants_by_status[BAD_SURVIVED]:
                    f.write('<h2>Survived</h2>')
                    f.write('Survived mutation testing. These mutants show holes in your test suite.')
                    print_diffs(BAD_SURVIVED)

                if mutants_by_status[OK_SUSPICIOUS]:
                    f.write('<h2>Suspicious</h2>')
                    f.write('Mutants that made the test suite take longer, but otherwise seemed ok')
                    print_diffs(OK_SUSPICIOUS)

                if mutants_by_status[SKIPPED]:
                    f.write('<h2>Skipped</h2>')
                    f.write('Mutants that were skipped')
                    print_diffs(SKIPPED)

                f.write('</body></html>')

        index_file.write('</table></body></html>')


U = TypeVar('U', bound=DbEntity)


def get_or_create(model: Type[U], defaults: Mapping[str, Any] | None = None, **params: Any) -> U:
    if defaults is None:
        defaults = {}
    obj = model.get(**params)
    if obj is None:
        params = params.copy()
        for k, v in defaults.items():
            if k not in params:
                params[k] = v
        return model(**params)
    else:
        return obj


def sequence_ops(a: list[str], b: list[str]) -> Iterator[tuple[str, str, int | None, str | None, int | None]]:
    sequence_matcher = SequenceMatcher(a=a, b=b)

    for tag, i1, i2, j1, j2 in sequence_matcher.get_opcodes():
        a_sub_sequence = a[i1:i2]
        b_sub_sequence = b[j1:j2]
        for x in zip_longest(a_sub_sequence, range(i1, i2), b_sub_sequence, range(j1, j2)):
            yield (tag,) + x


@init_db
@db_session
def update_line_numbers(filename: str) -> None:
    hash = hash_of(filename)
    sourcefile = get_or_create(SourceFile, filename=filename)
    if hash == sourcefile.hash:
        return
    cached_line_objects = list(sourcefile.lines.order_by(Line.line_number))

    cached_lines = [x.line for x in cached_line_objects if x.line is not None]
    assert len(cached_line_objects) == len(cached_lines)

    with open(filename) as f:
        existing_lines = [x.strip('\n') for x in f.readlines()]

    if not cached_lines:
        for i, line in enumerate(existing_lines):
            Line(sourcefile=sourcefile, line=line, line_number=i)
        return

    for command, _a, a_index, b, b_index in sequence_ops(cached_lines, existing_lines):
        if command == 'equal':
            assert isinstance(a_index, int)
            assert isinstance(b_index, int)
            if a_index != b_index:
                cached_obj = cached_line_objects[a_index]
                assert cached_obj.line == existing_lines[b_index]
                cached_obj.line_number = b_index

        elif command == 'delete':
            assert isinstance(a_index, int)
            cached_line_objects[a_index].delete()

        elif command == 'insert':
            if b is not None:
                assert isinstance(b_index, int)
                Line(sourcefile=sourcefile, line=b, line_number=b_index)

        elif command == 'replace':
            if a_index is not None:
                cached_line_objects[a_index].delete()
            if b is not None:
                assert isinstance(b_index, int)
                Line(sourcefile=sourcefile, line=b, line_number=b_index)

        else:
            raise ValueError('Unknown opcode from SequenceMatcher: {}'.format(command))

    sourcefile.hash = hash


@init_db
@db_session
def register_mutants(mutations_by_file: Dict[str, List[RelativeMutationID]]) -> None:
    for filename, mutation_ids in mutations_by_file.items():
        hash = hash_of(filename)
        sourcefile = get_or_create(SourceFile, filename=filename)
        if hash == sourcefile.hash:
            continue

        for mutation_id in mutation_ids:
            line = Line.get(sourcefile=sourcefile, line=mutation_id.line, line_number=mutation_id.line_number)
            if line is None:
                raise ValueError("Obtained null line for mutation_id: {}".format(mutation_id))
            get_or_create(Mutant, line=line, index=mutation_id.index, defaults=dict(status=UNTESTED))

        sourcefile.hash = hash


@init_db
@db_session
def update_mutant_status(file_to_mutate: str, mutation_id: RelativeMutationID, status: str, tests_hash: str) -> None:
    sourcefile = SourceFile.get(filename=file_to_mutate)
    line = Line.get(sourcefile=sourcefile, line=mutation_id.line, line_number=mutation_id.line_number)
    assert line is not None
    mutant = get_mutant(line=line, index=mutation_id.index)
    assert mutant, dict(line=line, index=mutation_id.index)
    mutant.status = status
    mutant.tested_against_hash = tests_hash


@init_db
@db_session
def get_cached_mutation_statuses(filename: str, mutations: List[RelativeMutationID], hash_of_tests: HashOfTestsStr) -> dict[RelativeMutationID, str]:
    sourcefile = SourceFile.get(filename=filename)
    assert sourcefile

    line_obj_by_line: dict[str, Line] = {}

    result: dict[RelativeMutationID, str] = {}

    for mutation_id in mutations:
        if mutation_id.line not in line_obj_by_line:
            line_from_db = Line.get(sourcefile=sourcefile, line=mutation_id.line, line_number=mutation_id.line_number)
            assert line_from_db is not None
            line_obj_by_line[mutation_id.line] = line_from_db
        line = line_obj_by_line[mutation_id.line]
        assert line
        mutant = get_mutant(line=line, index=mutation_id.index)
        if mutant is None:
            mutant = get_or_create(Mutant, line=line, index=mutation_id.index, defaults=dict(status=UNTESTED))

        result[mutation_id] = mutant.status
        if mutant.status == OK_KILLED:
            # We assume that if a mutant was killed, a change to the test
            # suite will mean it's still killed
            result[mutation_id] = mutant.status
        else:
            if mutant.tested_against_hash != hash_of_tests or \
                    mutant.tested_against_hash == NO_TESTS_FOUND or \
                    hash_of_tests == NO_TESTS_FOUND:
                result[mutation_id] = UNTESTED
            else:
                result[mutation_id] = mutant.status

    return result


@init_db
@db_session
def cached_mutation_status(filename: str, mutation_id: RelativeMutationID, hash_of_tests: HashOfTestsStr) -> str:
    assert isinstance(filename, str)  # guess
    assert isinstance(hash_of_tests, str)  # guess
    sourcefile = SourceFile.get(filename=filename)
    assert sourcefile
    line = Line.get(sourcefile=sourcefile, line=mutation_id.line, line_number=mutation_id.line_number)
    assert line
    mutant = get_mutant(line=line, index=mutation_id.index)
    if mutant is None:
        mutant = get_or_create(Mutant, line=line, index=mutation_id.index, defaults=dict(status=UNTESTED))

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
    return RelativeMutationID(line=mutant.line.line, index=mutant.index, line_number=mutant.line.line_number)


@init_db
@db_session
def filename_and_mutation_id_from_pk(pk: int | str) -> Tuple[str, RelativeMutationID]:
    if not isinstance(pk, (int, str)):  # pyright: ignore [reportUnnecessaryIsInstance]
        raise ValueError("filename_and_mutation_id_from_pk:", type(pk))
    mutant = get_mutant(id=pk)
    if mutant is None:
        raise ValueError("Obtained null mutant for pk: {}".format(pk))
    return mutant.line.sourcefile.filename, mutation_id_from_pk(pk)


@init_db
@db_session
def cached_test_time() -> float | None:
    d = MiscData.get(key='baseline_time_elapsed')
    if d:
        assert d.value is not None
        return float(d.value)
    return None


@init_db
@db_session
def set_cached_test_time(baseline_time_elapsed: float, current_hash_of_tests: str) -> None:
    get_or_create(MiscData, key='baseline_time_elapsed').value = str(baseline_time_elapsed)
    get_or_create(MiscData, key='hash_of_tests').value = current_hash_of_tests


@init_db
@db_session
def cached_hash_of_tests() -> str | None:
    d = MiscData.get(key='hash_of_tests')
    return d.value if d else None
