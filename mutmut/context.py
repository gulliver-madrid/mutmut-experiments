# -*- coding: utf-8 -*-
from __future__ import annotations

import os
from io import (
    open,
)
from typing import Optional

from parso.tree import NodeOrLeaf

from mutmut.config import Config
from mutmut.mutations import RelativeMutationID


ALL = RelativeMutationID(filename='%all%', line='%all%', index=-1, line_number=-1)


class Context:
    def __init__(
        self,
        source: Optional[str] = None,
        mutation_id: RelativeMutationID = ALL,
        dict_synonyms: list[str] | None = None,
        filename: str | None = None,
        config: Optional[Config] = None,
        index: int = 0,
    ):
        self.index = index
        self.remove_newline_at_end = False
        self._source = None
        self._set_source(source)
        self.mutation_id = mutation_id
        self.performed_mutation_ids: list[RelativeMutationID] = []
        assert isinstance(mutation_id, RelativeMutationID)
        self.current_line_index = 0
        self.filename = filename
        self.stack: list[NodeOrLeaf] = []
        self.dict_synonyms: list[str] = (dict_synonyms or []) + ['dict']
        self._source_by_line_number = None
        self._pragma_no_mutate_lines = None
        self._path_by_line = None
        self.config = config
        self.skip = False

    def exclude_line(self) -> bool:
        return self.current_line_index in self.pragma_no_mutate_lines or self. should_exclude()

    def should_exclude(self) -> bool:
        config = self.config
        if config is None or config.covered_lines_by_filename is None:
            return False

        try:
            covered_lines = config.covered_lines_by_filename[self.filename]
        except KeyError:
            if config.coverage_data is not None:
                covered_lines = config.coverage_data.get(os.path.abspath(self.filename))
                config.covered_lines_by_filename[self.filename] = covered_lines
            else:
                covered_lines = None

        if covered_lines is None:
            return True
        current_line = self.current_line_index + 1
        if current_line not in covered_lines:
            return True
        return False

    @property
    def source(self):
        if self._source is None:
            assert self.filename
            with open(self.filename) as f:
                self._set_source(f.read())
        return self._source

    def _set_source(self, source: str | None) -> None:
        if source and source[-1] != '\n':
            source += '\n'
            self.remove_newline_at_end = True
        self._source = source

    @property
    def source_by_line_number(self) -> list[str]:
        if self._source_by_line_number is None:
            assert self.source is not None
            self._source_by_line_number = self.source.split('\n')
        return self._source_by_line_number

    @property
    def current_source_line(self) -> str:
        return self.source_by_line_number[self.current_line_index]

    @property
    def mutation_id_of_current_index(self) -> RelativeMutationID:
        return RelativeMutationID(filename=self.filename, line=self.current_source_line, index=self.index, line_number=self.current_line_index)

    @property
    def pragma_no_mutate_lines(self) -> set[int]:
        if self._pragma_no_mutate_lines is None:
            self._pragma_no_mutate_lines = {
                i
                for i, line in enumerate(self.source_by_line_number)
                if '# pragma:' in line and 'no mutate' in line.partition('# pragma:')[-1]
            }
        return self._pragma_no_mutate_lines

    def should_mutate(self, node: NodeOrLeaf) -> bool:
        assert isinstance(node, NodeOrLeaf)
        if self.config and node.type not in self.config.mutation_types_to_apply:
            return False
        if self.mutation_id == ALL:
            return True
        return self.mutation_id in (ALL, self.mutation_id_of_current_index)
