from pathlib import Path

import pytest


@pytest.fixture
def testdata() -> Path:
    return Path(__file__).parent / "testdata"
