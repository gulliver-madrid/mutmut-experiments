from typing import Final, Literal, Mapping, TypeAlias


StatusStr: TypeAlias = Literal[
    "killed",
    "skipped",
    "survived",
    "suspicious",
    "timeout",
    "untested",
]

UNTESTED = 'untested'
OK_KILLED = 'ok_killed'
OK_SUSPICIOUS = 'ok_suspicious'
BAD_TIMEOUT = 'bad_timeout'
BAD_SURVIVED = 'bad_survived'
SKIPPED = 'skipped'


MUTANT_STATUSES: Final[Mapping[StatusStr, str]] = {
    "killed": OK_KILLED,
    "timeout": BAD_TIMEOUT,
    "suspicious": OK_SUSPICIOUS,
    "survived": BAD_SURVIVED,
    "skipped": SKIPPED,
    "untested": UNTESTED,
}
