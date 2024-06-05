from dataclasses import dataclass, field
from typing import Dict, Mapping, Optional, Set


from src.shared import HashStr, NoTestFoundSentinel
from src.utils import SequenceStr


@dataclass
class ConfigFlags:
    swallow_output: bool
    using_testmon: bool
    no_progress: bool
    ci: bool
    rerun_all: bool
    parallelize: bool


@dataclass
class DynamicCallbacks:
    post_mutation: str | None
    pre_mutation: str | None


@dataclass
class Config:
    test_command: str
    _default_test_command: str = field(init=False)
    covered_lines_by_filename: Optional[Dict[str, list[int]]]
    baseline_time_elapsed: float
    test_time_multiplier: float
    test_time_base: float
    dict_synonyms: SequenceStr
    total: int
    tests_dirs: SequenceStr
    hash_of_tests: HashStr | NoTestFoundSentinel
    coverage_data: Mapping[str, Mapping[int, SequenceStr]] | None
    paths_to_mutate: SequenceStr
    mutation_types_to_apply: Set[str]
    dynamic: DynamicCallbacks
    flags: ConfigFlags

    def __post_init__(self) -> None:
        self._default_test_command = self.test_command

    @property
    def default_test_command(self) -> str:
        return self._default_test_command
