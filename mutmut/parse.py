from typing import Any
import parso


def parse(code: str, **kwargs: Any) -> Any:
    """
    A wrapper for parso.parse.
    Params are documented in :py:meth:`parso.Grammar.parse`.

    :param str version: The version used by :py:func:`parso.load_grammar`.
    """
    return parso.parse(code, **kwargs)  # type: ignore [no-untyped-call]
