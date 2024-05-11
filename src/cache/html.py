# -*- coding: utf-8 -*-

import os
from collections import defaultdict
from io import open
from itertools import groupby
from os.path import join, dirname

from pony.orm import select

from src.cache.cache import get_unified_diff_from_filename_and_mutation_id, db_session, init_db
from src.cache.model import Mutant, get_mutants
from src.context import RelativeMutationID
from src.status import BAD_SURVIVED, BAD_TIMEOUT, OK_KILLED, OK_SUSPICIOUS, SKIPPED, StatusResultStr


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

                def print_diffs(status: StatusResultStr) -> None:
                    mutants = mutants_by_status[status]
                    for mutant in sorted(mutants, key=lambda m: m.id):
                        assert mutant.line.line is not None  # guess
                        mutation_id = RelativeMutationID(mutant.line.line, mutant.index, mutant.line.line_number)
                        diff = get_unified_diff_from_filename_and_mutation_id(source, filename, mutation_id, dict_synonyms, update_cache=False)
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
