# -*- coding: utf-8 -*-

from collections.abc import Sequence


def ranges(numbers: Sequence[int]) -> str:
    if not numbers:
        return ""

    result: list[str] = []
    start_range = numbers[0]
    end_range = numbers[0]

    def add_result():
        if start_range == end_range:
            result.append(str(start_range))
        else:
            result.append('{}-{}'.format(start_range, end_range))

    for x in numbers[1:]:
        if end_range + 1 == x:
            end_range = x
        else:
            add_result()

            start_range = x
            end_range = x

    add_result()

    return ', '.join(result)
