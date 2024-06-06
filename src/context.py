# -*- coding: utf-8 -*-
from __future__ import annotations

import os
from dataclasses import dataclass, field
from io import open
from typing import Final, Optional, Sequence

from parso.tree import NodeOrLeaf

from src.config import Config
from src.tools import configure_logger
from src.shared import FilenameStr
from src.storage import storage
from src.utils import SequenceStr, split_lines

logger = configure_logger(__name__)


@dataclass(frozen=True)
class RelativeMutationID:
    line: str
    index: int
    line_number: int
    filename: Optional[str] = field(default=None, compare=False, hash=False)


ALL = RelativeMutationID(filename="%all%", line="%all%", index=-1, line_number=-1)


class Context:
    mutated_source: str
    _source: str | None

    def __init__(
        self,
        source: Optional[str] = None,
        mutation_id: RelativeMutationID = ALL,
        dict_synonyms: SequenceStr | None = None,
        filename: FilenameStr | None = None,
        config: Optional[Config] = None,
        index: int = 0,
    ):
        self.index = index
        self.remove_newline_at_end = False
        self._set_source(source)
        self.mutation_id = mutation_id
        self.performed_mutation_ids: list[RelativeMutationID] = []
        assert isinstance(mutation_id, RelativeMutationID)
        self.current_line_index = 0
        self.filename: Final[FilenameStr | None] = filename
        self.stack: list[NodeOrLeaf] = []
        self.dict_synonyms: SequenceStr = list(dict_synonyms or []) + ["dict"]
        self._source_by_line_number: SequenceStr | None = None
        self._pragma_no_mutate_lines: set[int] | None = None
        self.config = config
        self.skip: bool = False

    def exclude_line(self) -> bool:
        return (
            self.current_line_index in self.pragma_no_mutate_lines
            or self.should_exclude()
        )

    def should_exclude(self) -> bool:
        config = self.config
        if config is None or config.covered_lines_by_filename is None:
            return False

        assert self.filename is not None
        covered_lines: Sequence[int] | None = config.covered_lines_by_filename.get(
            self.filename
        )

        if covered_lines is None and config.coverage_data is not None:
            covered_lines = self._get_covered_lines_from_coverage_data()
            config.covered_lines_by_filename[self.filename] = covered_lines

        if not covered_lines:
            return True

        current_line = self.current_line_index + 1
        return current_line not in covered_lines

    def _get_covered_lines_from_coverage_data(self) -> list[int]:
        assert self.config
        assert self.config.coverage_data is not None
        assert self.filename is not None
        abspath = os.path.abspath(self.filename)
        covered_lines_as_dict = self.config.coverage_data.get(abspath, {})
        return list(covered_lines_as_dict.keys())

    @property
    def source(self) -> str:
        if self._source is None:
            assert self.filename
            with open(
                storage.project_path.get_current_project_path() / self.filename
            ) as f:
                self._set_source(f.read())
        assert self._source is not None
        return self._source

    def _set_source(self, source: str | None) -> None:
        if source and source[-1] != "\n":
            source += "\n"
            self.remove_newline_at_end = True
        self._source = source

    @property
    def source_by_line_number(self) -> SequenceStr:
        if self._source_by_line_number is None:
            assert self.source is not None
            self._source_by_line_number = split_lines(self.source)
        return self._source_by_line_number

    @property
    def current_source_line(self) -> str:
        return self.source_by_line_number[self.current_line_index]

    @property
    def mutation_id_of_current_index(self) -> RelativeMutationID:
        return RelativeMutationID(
            filename=self.filename,
            line=self.current_source_line,
            index=self.index,
            line_number=self.current_line_index,
        )

    @property
    def pragma_no_mutate_lines(self) -> set[int]:
        if self._pragma_no_mutate_lines is None:
            self._pragma_no_mutate_lines = {
                i
                for i, line in enumerate(self.source_by_line_number)
                if "# pragma:" in line
                and "no mutate" in line.partition("# pragma:")[-1]
            }
        return self._pragma_no_mutate_lines

    def should_mutate(self, node: NodeOrLeaf) -> bool:
        assert isinstance(node, NodeOrLeaf)
        if self.config and node.type not in self.config.mutation_types_to_apply:
            return False
        if self.mutation_id == ALL:
            return True
        return self.mutation_id in (ALL, self.mutation_id_of_current_index)
