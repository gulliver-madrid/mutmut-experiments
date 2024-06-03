# -*- coding: utf-8 -*-
import multiprocessing
from typing import Literal, NewType, TypeAlias

from src.context import Context, RelativeMutationID
from src.shared import FilenameStr
from src.status import StatusResultStr

ProcessId = NewType("ProcessId", int)

_MutantQueueItem: TypeAlias = (
    tuple[Literal["mutant"], Context] | tuple[Literal["end"], None]
)
MutantQueue: TypeAlias = "multiprocessing.Queue[_MutantQueueItem]"
_ResultQueueItem: TypeAlias = (
    tuple[
        Literal["status"], None, StatusResultStr, FilenameStr | None, RelativeMutationID
    ]
    | tuple[Literal["progress"], None, str, None, None]
    | tuple[Literal["end"], ProcessId, None, None, None]
    | tuple[Literal["cycle"], ProcessId, None, None, None]
)
ResultQueue: TypeAlias = "multiprocessing.Queue[_ResultQueueItem]"
