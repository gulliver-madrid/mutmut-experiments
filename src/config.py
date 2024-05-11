from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from src.cache.model import HashStr, NoTestFoundSentinel


@dataclass
class Config:
    swallow_output: bool
    test_command: str
    _default_test_command: str = field(init=False)
    covered_lines_by_filename: Optional[Dict[str, list[int]]]
    baseline_time_elapsed: float
    test_time_multiplier: float
    test_time_base: float
    dict_synonyms: List[str]
    total: int
    using_testmon: bool
    tests_dirs: List[str]
    hash_of_tests: HashStr | NoTestFoundSentinel
    post_mutation: str | None
    pre_mutation: str | None
    coverage_data: Dict[str, Dict[int, List[str]]] | None
    paths_to_mutate: List[str]
    mutation_types_to_apply: Set[str]
    no_progress: bool
    ci: bool
    rerun_all: bool

    def __post_init__(self) -> None:
        self._default_test_command = self.test_command

    @property
    def default_test_command(self) -> str:
        return self._default_test_command
