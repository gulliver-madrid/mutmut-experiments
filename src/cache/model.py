# -*- coding: utf-8 -*-


from dataclasses import field
from typing import (
    TYPE_CHECKING,
    Any,
    Final,
    Iterable,
    Literal,
    Mapping,
    NewType,
    Type,
    overload,
    TypeVar,
)

from pony.orm import Database, Required, Set, Optional, PrimaryKey
from typing_extensions import Self

from src.shared import FilenameStr
from src.status import StatusResultStr

HashStr = NewType("HashStr", str)

NO_TESTS_FOUND: Final = "NO TESTS FOUND"

NoTestFoundSentinel = Literal["NO TESTS FOUND"]

db = Database()


if TYPE_CHECKING:

    class DbEntity:
        @classmethod
        def get(cls, **kwargs: Any) -> Self | None: ...

else:
    DbEntity = db.Entity


class MiscData(DbEntity):
    key = PrimaryKey(str, auto=True)
    value = Optional(str, autostrip=False)


if TYPE_CHECKING:

    class SourceFile(DbEntity):
        filename: FilenameStr
        hash: HashStr | None
        lines: Set["Line"]

else:

    class SourceFile(DbEntity):  # type: ignore [valid-type]
        filename = Required(str, autostrip=False)
        hash = Optional(str)
        lines = Set("Line")


if TYPE_CHECKING:

    class Line(DbEntity):
        sourcefile: SourceFile
        line: str | None
        line_number: int
        mutants: Set["Mutant"]

        def __init__(self, *, sourcefile: Any, line: str, line_number: int) -> None: ...

        def delete(self) -> None: ...

else:

    class Line(DbEntity):  # type: ignore [valid-type]
        sourcefile = Required(SourceFile)
        line = Optional(str, autostrip=False)
        line_number = Required(int)
        mutants = Set("Mutant")


if TYPE_CHECKING:
    from dataclasses import dataclass

    @dataclass
    class Mutant(DbEntity):
        line: Line
        index: int
        status: StatusResultStr
        tested_against_hash: str | None = field(default=None)
        id: int = field(default=0)

else:

    class Mutant(DbEntity):
        line = Required(Line)
        index = Required(int)
        tested_against_hash = Optional(str, autostrip=False)
        status = Required(str, autostrip=False)  # really an enum of mutant_statuses


def get_mutants() -> Iterable[Mutant]:
    return Mutant  # type: ignore [return-value]


@overload
def get_mutant(*, id: int | str) -> Mutant | None: ...


@overload
def get_mutant(*, line: Line, index: int) -> Mutant | None: ...


def get_mutant(**kwargs: Any) -> Mutant | None:
    return Mutant.get(**kwargs)


U = TypeVar("U", bound=DbEntity)


def get_or_create(
    model: Type[U], defaults: Mapping[str, Any] | None = None, **params: Any
) -> U:
    if defaults is None:
        defaults = {}
    obj = model.get(**params)
    if obj is None:
        params = params.copy()
        for k, v in defaults.items():
            if k not in params:
                params[k] = v
        return model(**params)
    else:
        return obj
