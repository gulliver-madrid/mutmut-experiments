# -*- coding: utf-8 -*-


from io import open
from itertools import groupby
from typing import TYPE_CHECKING, Sequence

from pony.orm import select

from mutmut.cache.cache import db_session, get_unified_diff, init_db
from mutmut.cache.model import Mutant, get_mutants
from mutmut.utils import ranges
from mutmut.status import BAD_SURVIVED, BAD_TIMEOUT, MUTANT_STATUSES, OK_SUSPICIOUS, SKIPPED, UNTESTED, StatusResultStr, StatusStr

if TYPE_CHECKING:
    from pony.orm import Query


@init_db
@db_session
def print_result_cache(show_diffs: bool = False, dict_synonyms: list[str] = [], only_this_file: str | None = None) -> None:
    print('To apply a mutant on disk:')
    print('    mutmut apply <id>')
    print('')
    print('To show a mutant:')
    print('    mutmut show <id>')
    print('')

    def print_stuff(title: str, mutant_query: 'Query[Mutant, Mutant]') -> None:
        mutant_list = sorted(mutant_query, key=lambda x: x.line.sourcefile.filename)

        if not mutant_list:
            return

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
    print_stuff('Timed out ⏰', select_mutants_by_status(BAD_TIMEOUT))
    print_stuff('Suspicious 🤔', select_mutants_by_status(OK_SUSPICIOUS))
    print_stuff('Survived 🙁', select_mutants_by_status(BAD_SURVIVED))
    print_stuff('Untested/skipped', select_mutants_by_status((UNTESTED, SKIPPED)))


@init_db
@db_session
def print_result_ids_cache(desired_status: StatusStr) -> None:
    status = MUTANT_STATUSES[desired_status]
    mutant_query = select(x for x in get_mutants() if x.status == status)
    print(" ".join(str(mutant.id) for mutant in mutant_query))


def select_mutants_by_status(status: StatusResultStr | Sequence[StatusResultStr]) -> 'Query[Mutant, Mutant]':
    if isinstance(status, str):
        status = (status,)
    return select(x for x in get_mutants() if x.status in status)
