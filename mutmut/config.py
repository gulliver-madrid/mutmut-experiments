from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set


@dataclass
class Config:
    swallow_output: bool
    test_command: str
    _default_test_command: str = field(init=False)
    covered_lines_by_filename: Optional[Dict[str, Optional[list[Optional[int]]]]]
    baseline_time_elapsed: float
    test_time_multiplier: float
    test_time_base: float
    dict_synonyms: List[str]
    total: int
    using_testmon: bool
    tests_dirs: List[str]
    hash_of_tests: str
    post_mutation: str
    pre_mutation: str
    coverage_data: Dict[str, Dict[int, List[str]]] | None
    paths_to_mutate: List[str]
    mutation_types_to_apply: Set[str]
    no_progress: bool
    ci: bool
    rerun_all: bool

    def __post_init__(self) -> None:
        self._default_test_command = self.test_command
