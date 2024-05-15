import os
from typing import Dict, List, Mapping, TypeAlias

from src.project import project_path_storage


FilePathStr: TypeAlias = str
ContextsByLineNo: TypeAlias = Dict[int, List[str]]


def read_coverage_data() -> Dict[FilePathStr, ContextsByLineNo]:
    """
    Reads the coverage database and returns a dictionary which maps the filenames to the covered lines and their contexts.
    """
    try:
        # noinspection PyPackageRequirements,PyUnresolvedReferences
        from coverage import Coverage
    except ImportError as e:
        raise ImportError(
            'The --use-coverage feature requires the coverage library. Run "pip install --force-reinstall mutmut[coverage]"'
        ) from e
    cov = Coverage(str(project_path_storage.get_current_project_path() / ".coverage"))
    cov.load()
    data = cov.get_data()
    return {
        filepath: data.contexts_by_lineno(filepath)
        for filepath in data.measured_files()
    }


def check_coverage_data_filepaths(
    coverage_data: Mapping[FilePathStr, ContextsByLineNo]
) -> None:
    for filepath in coverage_data:
        if not os.path.exists(filepath):
            raise ValueError(
                "Filepaths in .coverage not recognized, try recreating the .coverage file manually."
            )
