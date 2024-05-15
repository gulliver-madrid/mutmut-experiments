# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Mapping


from src.status import (
    BAD_SURVIVED,
    BAD_TIMEOUT,
    OK_KILLED,
    OK_SUSPICIOUS,
    SKIPPED,
    StatusResultStr,
)
from src.utils import print_status


class Progress:
    def __init__(
        self, total: int, output_legend: Mapping[str, str], no_progress: bool = False
    ):
        self.total = total
        self.output_legend = output_legend
        self.progress = 0
        self.skipped = 0
        self.killed_mutants = 0
        self.surviving_mutants = 0
        self.surviving_mutants_timeout = 0
        self.suspicious_mutants = 0
        self.no_progress = no_progress

    def print(self) -> None:
        if self.no_progress:
            return
        print_status(
            "{}/{}  {} {}  {} {}  {} {}  {} {}  {} {}".format(
                self.progress,
                self.total,
                self.output_legend["killed"],
                self.killed_mutants,
                self.output_legend["timeout"],
                self.surviving_mutants_timeout,
                self.output_legend["suspicious"],
                self.suspicious_mutants,
                self.output_legend["survived"],
                self.surviving_mutants,
                self.output_legend["skipped"],
                self.skipped,
            )
        )

    def register(self, status: StatusResultStr) -> None:
        if status == BAD_SURVIVED:
            self.surviving_mutants += 1
        elif status == BAD_TIMEOUT:
            self.surviving_mutants_timeout += 1
        elif status == OK_KILLED:
            self.killed_mutants += 1
        elif status == OK_SUSPICIOUS:
            self.suspicious_mutants += 1
        elif status == SKIPPED:
            self.skipped += 1
        else:
            raise ValueError(
                "Unknown status returned from run_mutation: {}".format(status)
            )
        self.progress += 1
        self.print()
