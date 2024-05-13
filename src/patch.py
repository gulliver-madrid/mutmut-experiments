import os
from pathlib import Path
from typing import Dict, TYPE_CHECKING


CoveredLinesByFilename = Dict[str, list[int]]


if TYPE_CHECKING:
    from whatthepatch.patch import diffobj


def get_new_path(diff: "diffobj") -> str:
    assert diff.header is not None
    return diff.header.new_path


def read_patch_data(patch_file_path: str | Path) -> CoveredLinesByFilename:
    try:
        # noinspection PyPackageRequirements
        import whatthepatch
    except ImportError as e:
        raise ImportError(
            'The --use-patch feature requires the whatthepatch library. Run "pip install --force-reinstall mutmut[patch]"'
        ) from e

    with open(patch_file_path) as f:
        diffs = whatthepatch.parse_patch(f.read())

    result = {
        os.path.normpath(get_new_path(diff)): sorted(
            {
                change.new
                for change in diff.changes
                if change.old is None and change.new is not None
            }
        )
        for diff in diffs
        if diff.changes
    }
    return result
