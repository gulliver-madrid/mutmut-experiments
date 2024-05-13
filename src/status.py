from typing import Final, Literal, Mapping, TypeAlias


StatusStr: TypeAlias = Literal[
    "killed",
    "skipped",
    "survived",
    "suspicious",
    "timeout",
    "untested",
]

StatusResultStr: TypeAlias = Literal[
    "untested",
    "ok_killed",
    "ok_suspicious",
    "bad_timeout",
    "bad_survived",
    "skipped",
]

UNTESTED: Final = "untested"
OK_KILLED: Final = "ok_killed"
OK_SUSPICIOUS: Final = "ok_suspicious"
BAD_TIMEOUT: Final = "bad_timeout"
BAD_SURVIVED: Final = "bad_survived"
SKIPPED: Final = "skipped"


MUTANT_STATUSES: Final[Mapping[StatusStr, StatusResultStr]] = {
    "killed": OK_KILLED,
    "timeout": BAD_TIMEOUT,
    "suspicious": OK_SUSPICIOUS,
    "survived": BAD_SURVIVED,
    "skipped": SKIPPED,
    "untested": UNTESTED,
}
