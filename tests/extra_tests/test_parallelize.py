# -*- coding: utf-8 -*-

import builtins
import os

from click.testing import CliRunner

from src import (
    __version__,
)
from src.__main__ import climain

from helpers import FileSystemPath, open_utf8
from fixtures_main import (
    FILE_TO_MUTATE_CONTENTS,
    filesystem,  # pyright: ignore [reportUnusedImport]
)

builtins.open = open_utf8  # type: ignore [assignment]


def test_simple_parallelize(filesystem: FileSystemPath) -> None:
    result = CliRunner().invoke(
        climain,
        ["run", "-s", "--paths-to-mutate=foo.py", "--parallelize"],
        catch_exceptions=False,
    )
    print(repr(result.output))
    assert result.exit_code == 0

    result = CliRunner().invoke(climain, ["apply", "1"], catch_exceptions=False)
    print(repr(result.output))
    assert result.exit_code == 0

    with open(os.path.join(str(filesystem), "foo.py")) as f:
        # print()
        # print(f"{f.read()=}")
        # print(f"{FILE_TO_MUTATE_CONTENTS=}")
        assert f.read() != FILE_TO_MUTATE_CONTENTS
