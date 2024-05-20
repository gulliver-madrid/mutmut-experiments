from pathlib import Path

from click.testing import CliRunner

from src.__main__ import climain

from fixtures import (
    surviving_mutants_filesystem,  # pyright: ignore [reportUnusedImport]
)


def test_html_output_not_slow(surviving_mutants_filesystem: Path) -> None:
    CliRunner().invoke(
        climain,
        ["run", "--paths-to-mutate=foo.py", "--test-time-base=15.0"],
        catch_exceptions=False,
    )
    import time

    t = time.time()
    CliRunner().invoke(climain, ["html"])
    elapsed = time.time() - t
    assert elapsed < 0.2
