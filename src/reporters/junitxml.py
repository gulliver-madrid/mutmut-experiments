# -*- coding: utf-8 -*-


from itertools import groupby
from typing import Any

from junit_xml import TestSuite, TestCase, to_xml_report_string  # type: ignore [import-untyped]
from pony.orm import select

from src.cache.cache import get_unified_diff
from src.cache.db_core import db_session, init_db
from src.cache.model import get_mutants
from src.shared import PolicyStr
from src.status import BAD_SURVIVED, BAD_TIMEOUT, OK_SUSPICIOUS, UNTESTED
from src.utils import SequenceStr


def print_result_cache_junitxml(
    dict_synonyms: SequenceStr, suspicious_policy: PolicyStr, untested_policy: PolicyStr
) -> None:
    print(create_junitxml_report(dict_synonyms, suspicious_policy, untested_policy))


@init_db
@db_session
def create_junitxml_report(
    dict_synonyms: SequenceStr, suspicious_policy: PolicyStr, untested_policy: PolicyStr
) -> str:
    test_cases: list[TestCase] = []
    mutant_list = list(select(x for x in get_mutants()))
    for filename, mutants in groupby(
        mutant_list, key=lambda x: x.line.sourcefile.filename
    ):
        for mutant in mutants:
            tc: Any = TestCase(
                "Mutant #{}".format(mutant.id),
                file=filename,
                line=mutant.line.line_number + 1,
                stdout=mutant.line.line,
            )
            if mutant.status == BAD_SURVIVED:
                tc.add_failure_info(
                    message=mutant.status,
                    output=get_unified_diff(mutant.id, dict_synonyms),
                )
            elif mutant.status == BAD_TIMEOUT:
                tc.add_error_info(
                    message=mutant.status,
                    error_type="timeout",
                    output=get_unified_diff(mutant.id, dict_synonyms),
                )
            elif mutant.status == OK_SUSPICIOUS:
                if suspicious_policy != "ignore":
                    func = getattr(tc, "add_{}_info".format(suspicious_policy))
                    func(
                        message=mutant.status,
                        output=get_unified_diff(mutant.id, dict_synonyms),
                    )
            elif mutant.status == UNTESTED:
                if untested_policy != "ignore":
                    func = getattr(tc, "add_{}_info".format(untested_policy))
                    func(
                        message=mutant.status,
                        output=get_unified_diff(mutant.id, dict_synonyms),
                    )

            test_cases.append(tc)

    ts = TestSuite("mutmut", test_cases)
    report: Any = to_xml_report_string([ts])
    assert isinstance(report, str)
    return report
