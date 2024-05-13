import os
from pathlib import Path
from typing import Dict, Mapping, TypeGuard, cast, TYPE_CHECKING


CoveredLinesByFilename = Dict[str, set[int]]


def is_covered_lines_by_filename(obj: object) -> TypeGuard[CoveredLinesByFilename]:
    if not isinstance(obj, dict):
        return False
    d = cast(Mapping[object, object], obj)
    if not all(isinstance(k, str) for k in d.keys()):
        return False
    for v in d.values():
        if not isinstance(v, set):
            return False
        covered_lines = cast(frozenset[object], v)
        if not all(isinstance(item, int) for item in covered_lines):
            return False
    return True


if TYPE_CHECKING:
    from whatthepatch.patch import diffobj


def get_new_path(diff: 'diffobj') -> str:
    assert diff.header is not None
    return diff.header.new_path


def read_patch_data(patch_file_path: str | Path) -> CoveredLinesByFilename:
    try:
        # noinspection PyPackageRequirements
        import whatthepatch
    except ImportError as e:
        raise ImportError('The --use-patch feature requires the whatthepatch library. Run "pip install --force-reinstall mutmut[patch]"') from e

    with open(patch_file_path) as f:
        diffs = whatthepatch.parse_patch(f.read())

    result = {
        os.path.normpath(get_new_path(diff)): {change.new for change in diff.changes if change.old is None}
        for diff in diffs if diff.changes
    }
    assert is_covered_lines_by_filename(result)
    return result
