# -*- coding: utf-8 -*-

from difflib import SequenceMatcher
from io import open
from itertools import zip_longest
from typing import (
    Iterator,
    Literal,
    cast,
)


from src.cache.db_core import db_session, init_db
from src.cache.hash import hash_of
from src.shared import FilenameStr
from src.utils import SequenceStr

from .model import (
    Line,
    SourceFile,
    get_or_create,
)


Tag = Literal["replace", "delete", "insert", "equal"]


def cast_tag(tag: str) -> Tag:
    assert tag in ["replace", "delete", "insert", "equal"]
    return cast(Tag, tag)


def sequence_ops(
    a: SequenceStr, b: SequenceStr
) -> Iterator[tuple[Tag, str, int | None, str | None, int | None]]:
    sequence_matcher = SequenceMatcher(a=a, b=b)

    for tag_, i1, i2, j1, j2 in sequence_matcher.get_opcodes():
        tag = cast_tag(tag_)
        a_sub_sequence = a[i1:i2]
        b_sub_sequence = b[j1:j2]
        for x in zip_longest(
            a_sub_sequence, range(i1, i2), b_sub_sequence, range(j1, j2)
        ):
            yield (tag,) + x


@init_db
@db_session
def update_line_numbers(filename: FilenameStr) -> None:
    hash = hash_of(filename)
    sourcefile = get_or_create(SourceFile, filename=filename)
    if hash == sourcefile.hash:
        return
    cached_line_objects = list(sourcefile.lines.order_by(Line.line_number))

    cached_lines = [x.line for x in cached_line_objects if x.line is not None]
    assert len(cached_line_objects) == len(cached_lines)

    with open(filename) as f:
        existing_lines = [x.strip("\n") for x in f.readlines()]

    if not cached_lines:
        for i, line in enumerate(existing_lines):
            Line(sourcefile=sourcefile, line=line, line_number=i)
        return

    for command, _a, a_index, b, b_index in sequence_ops(cached_lines, existing_lines):
        if command == "equal":
            assert isinstance(a_index, int)
            assert isinstance(b_index, int)
            if a_index != b_index:
                cached_obj = cached_line_objects[a_index]
                assert cached_obj.line == existing_lines[b_index]
                cached_obj.line_number = b_index

        elif command == "delete":
            assert isinstance(a_index, int)
            cached_line_objects[a_index].delete()

        elif command == "insert":
            if b is not None:
                assert isinstance(b_index, int)
                Line(sourcefile=sourcefile, line=b, line_number=b_index)

        elif command == "replace":
            if a_index is not None:
                cached_line_objects[a_index].delete()
            if b is not None:
                assert isinstance(b_index, int)
                Line(sourcefile=sourcefile, line=b, line_number=b_index)

        else:
            raise ValueError("Unknown opcode from SequenceMatcher: {}".format(command))

    sourcefile.hash = hash
