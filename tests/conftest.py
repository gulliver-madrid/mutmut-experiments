from pathlib import Path
from typing import Iterator

import pytest

from mutmut.mut_config_storage import reset_global_vars


def clear_db() -> None:
    # This is a hack to get pony to forget about the old db file
    # otherwise Pony thinks we've already created the tables
    import mutmut.cache.model as cache
    cache.db.provider = None
    cache.db.schema = None

@pytest.fixture
def testdata() -> Path:
    return Path(__file__).parent / "testdata"

@pytest.fixture(autouse=True)
def reset_state() -> Iterator[None]:
    reset_global_vars()
    clear_db()
    yield
