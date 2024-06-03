# We have a global whitelist for constants of the pattern __all__, __version__, etc

from typing import Final

from src.utils import SequenceStr


dunder_whitelist: Final[SequenceStr] = [
    "all",
    "version",
    "title",
    "package_name",
    "author",
    "description",
    "email",
    "version",
    "license",
    "copyright",
]


def is_dunder_name(name: str) -> bool:
    return (
        name.startswith("__") and name.endswith("__") and name[2:-2] in dunder_whitelist
    )
