# -*- coding: utf-8 -*-

import os
import sys
import traceback
from pathlib import Path
from shutil import copy
from time import time
from types import NoneType

import click
from glob2 import glob  # type: ignore [import-untyped]

from src.dir_context import DirContext
from src.process import popen_streaming_output
from src.progress import Progress
from src.setup_logging import configure_logger
from src.shared import FilenameStr

# ensure mutmut modules are detected
base = Path(__file__).parent.parent
if str(base) not in sys.path:
    sys.path.insert(0, str(base))

from src import (
    __version__,
    guess_paths_to_mutate,
    add_mutations_by_file,
    python_source_files,
    compute_exit_code,
)
from src.cache.cache import (
    MutationsByFile,
    cached_hash_of_tests,
    hash_of_tests,
    filename_and_mutation_id_from_pk,
    cached_test_time,
    set_cached_test_time,
    update_line_numbers,
)
from src.config import Config
from src.coverage import check_coverage_data_filepaths, read_coverage_data
from src.mutation_test_runner import MutationTestsRunner
from src.mutations import mutations_by_type
from src.dynamic_config_storage import (
    DYNAMIC_CONFIG_NOT_DEFINED,
    user_dynamic_config_storage,
)
from src.patch import CoveredLinesByFilename, read_patch_data
from src.project import project_path_storage, temp_dir_storage
from src.utils import (
    SequenceStr,
    copy_directory,
    split_lines,
    split_paths,
    print_status,
)

logger = configure_logger(__name__)

DEFAULT_RUNNER = "python -m pytest -x --assert=plain"


def do_run(
    argument: str | None,
    paths_to_mutate: str | None | list[str] | tuple[str, ...],
    disable_mutation_types: str | None,
    enable_mutation_types: str | None,
    runner: str | None,
    tests_dir: str | None,
    test_time_multiplier: float,
    test_time_base: float,
    swallow_output: bool | None,
    use_coverage: bool | None,
    dict_synonyms: str,
    pre_mutation: str | None,
    post_mutation: str | None,
    use_patch_file: str | None,
    paths_to_exclude: str,
    simple_output: bool | None,
    no_progress: bool | None,
    ci: bool | None,
    rerun_all: bool | None,
    project: str | None,
    parallelize: bool,
) -> int:
    """return exit code, after performing an mutation test run.

    :return: the exit code from executing the mutation tests for run command
    """

    # CHECK TYPES START
    assert isinstance(argument, (str, NoneType))
    assert isinstance(disable_mutation_types, (str, NoneType)), disable_mutation_types
    assert isinstance(enable_mutation_types, (str, NoneType)), enable_mutation_types
    assert isinstance(paths_to_mutate, (str, NoneType))
    assert isinstance(runner, str), runner  # guess
    assert isinstance(tests_dir, (str, NoneType))
    assert isinstance(test_time_multiplier, float)
    assert isinstance(test_time_base, float)
    assert isinstance(swallow_output, (bool, NoneType)), swallow_output
    assert isinstance(use_coverage, (bool, NoneType)), use_coverage
    assert isinstance(dict_synonyms, str), dict_synonyms
    assert isinstance(pre_mutation, (str, NoneType)), pre_mutation
    assert isinstance(post_mutation, (str, NoneType)), post_mutation
    assert isinstance(use_patch_file, (str, NoneType)), use_patch_file
    assert isinstance(paths_to_exclude, str)
    assert isinstance(simple_output, (bool, NoneType)), simple_output
    assert isinstance(no_progress, (bool, NoneType)), no_progress
    assert isinstance(ci, (bool, NoneType))
    assert isinstance(rerun_all, (bool, NoneType)), rerun_all
    assert isinstance(project, (str, NoneType))
    assert isinstance(parallelize, bool)
    # CHECK TYPES END

    print(f"Paths to mutate: {paths_to_mutate}")
    print(f"Tests directory: {tests_dir}")
    print(f"Runner: {runner}")
    print(f"Project: {project}")
    print(f"{swallow_output=}")

    project_path_storage.set_project_path(project)
    project_path = project_path_storage.get_project_path()
    user_dynamic_config_storage.clear_dynamic_config_cache()
    dynamic_config = user_dynamic_config_storage.get_dynamic_config()

    print(
        f"Dynamic config config found: {dynamic_config not in (None,DYNAMIC_CONFIG_NOT_DEFINED)}"
    )

    no_progress = no_progress or False

    if use_coverage and use_patch_file:
        raise click.BadArgumentUsage("You can't combine --use-coverage and --use-patch")

    if disable_mutation_types and enable_mutation_types:
        raise click.BadArgumentUsage(
            "You can't combine --disable-mutation-types and --enable-mutation-types"
        )
    if enable_mutation_types:
        mutation_types_to_apply = set(
            mtype.strip() for mtype in enable_mutation_types.split(",")
        )
        invalid_types = [
            mtype for mtype in mutation_types_to_apply if mtype not in mutations_by_type
        ]
    elif disable_mutation_types:
        mutation_types_to_apply = set(mutations_by_type.keys()) - set(
            mtype.strip() for mtype in disable_mutation_types.split(",")
        )
        invalid_types = [
            mtype
            for mtype in disable_mutation_types.split(",")
            if mtype not in mutations_by_type
        ]
    else:
        mutation_types_to_apply = set(mutations_by_type.keys())
        invalid_types = None
    if invalid_types:
        raise click.BadArgumentUsage(
            f"The following are not valid mutation types: {', '.join(sorted(invalid_types))}. Valid mutation types are: {', '.join(mutations_by_type.keys())}"
        )

    dict_synonyms_as_sequence: SequenceStr = dict_synonyms_to_list(dict_synonyms)

    if (
        use_coverage
        and not (project_path_storage.get_current_project_path() / ".coverage").exists()
    ):
        raise FileNotFoundError(
            "No .coverage file found. You must generate a coverage file to use this feature."
        )

    if paths_to_mutate is None:
        paths_to_mutate = guess_paths_to_mutate()
    assert isinstance(paths_to_mutate, str)

    paths_to_mutate = split_paths(
        paths_to_mutate, project_path_storage.get_current_project_path()
    )

    if not paths_to_mutate:
        raise click.BadOptionUsage(
            "--paths-to-mutate",
            "You must specify a list of paths to mutate."
            "Either as a command line argument, or by setting paths_to_mutate under the section [mutmut] in setup.cfg."
            "To specify multiple paths, separate them with commas or colons (i.e: --paths-to-mutate=path1/,path2/path3/,path4/).",
        )

    assert tests_dir is not None
    test_paths = split_paths(tests_dir, project_path_storage.get_current_project_path())
    if not test_paths:
        raise FileNotFoundError(
            'No test folders found in current folder. Run this where there is a "tests" or "test" folder.'
        )

    tests_dirs = _get_tests_dirs(
        paths_to_mutate=paths_to_mutate,
        test_paths=test_paths,
    )

    current_hash_of_tests = hash_of_tests(tests_dirs)

    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"  # stop python from creating .pyc files

    using_testmon = "--testmon" in runner
    output_legend = {
        "killed": "🎉",
        "timeout": "⏰",
        "suspicious": "🤔",
        "survived": "🙁",
        "skipped": "🔇",
    }
    if simple_output:
        output_legend = {key: key.upper() for key in output_legend.keys()}

    print(
        """
- Mutation testing starting -

These are the steps:
1. A full test suite run will be made to make sure we
   can run the tests successfully and we know how long
   it takes (to detect infinite loops for example)
2. Mutants will be generated and checked

Results are stored in .mutmut-cache.
Print found mutants with `mutmut results`.

Legend for output:
{killed} Killed mutants.   The goal is for everything to end up in this bucket.
{timeout} Timeout.          Test suite took 10 times as long as the baseline so were killed.
{suspicious} Suspicious.       Tests took a long time, but not long enough to be fatal.
{survived} Survived.         This means your tests need to be expanded.
{skipped} Skipped.          Skipped.
""".format(
            **output_legend
        )
    )
    if runner is DEFAULT_RUNNER:
        try:
            import pytest  # noqa
        except ImportError:
            runner = "python -m unittest"

    if hasattr(dynamic_config, "init"):
        dynamic_config.init()

    directory = (
        project_path_storage.get_current_project_path()
        if project_path
        else Path(os.getcwd())
    )

    with DirContext(directory):
        baseline_time_elapsed = time_test_suite(
            swallow_output=not swallow_output,
            test_command=runner,
            using_testmon=using_testmon,
            current_hash_of_tests=current_hash_of_tests,
            no_progress=no_progress,
        )

    if using_testmon:
        copy(".testmondata", ".testmondata-initial")

    # if we're running in a mode with externally whitelisted lines
    covered_lines_by_filename: CoveredLinesByFilename | None = None

    coverage_data = None
    if use_coverage:
        covered_lines_by_filename = {}
        coverage_data = read_coverage_data()
        check_coverage_data_filepaths(coverage_data)
    elif use_patch_file:
        covered_lines_by_filename = read_patch_data(use_patch_file)

    mutations_by_file: MutationsByFile = {}

    paths_to_exclude = paths_to_exclude or ""
    paths_to_exclude_as_list: SequenceStr
    if paths_to_exclude:
        paths_to_exclude_as_list = [
            path.strip() for path in split_lines(paths_to_exclude.replace(",", "\n"))
        ]
        paths_to_exclude_as_list = [x for x in paths_to_exclude_as_list if x]
    else:
        paths_to_exclude_as_list = []

    ci = bool(ci)

    config = Config(
        total=0,  # we'll fill this in later!
        swallow_output=not swallow_output,
        test_command=runner,
        covered_lines_by_filename=covered_lines_by_filename,
        coverage_data=coverage_data,
        baseline_time_elapsed=baseline_time_elapsed,
        dict_synonyms=dict_synonyms_as_sequence,
        using_testmon=using_testmon,
        tests_dirs=tests_dirs,
        hash_of_tests=current_hash_of_tests,
        test_time_multiplier=test_time_multiplier,
        test_time_base=test_time_base,
        pre_mutation=pre_mutation,
        post_mutation=post_mutation,
        paths_to_mutate=paths_to_mutate,
        mutation_types_to_apply=mutation_types_to_apply,
        no_progress=no_progress,
        ci=ci,
        rerun_all=bool(rerun_all),
        parallelize=parallelize,
    )

    parse_run_argument(
        argument,
        config,
        dict_synonyms_as_sequence,
        mutations_by_file,
        paths_to_exclude_as_list,
        paths_to_mutate,
        tests_dirs,
    )

    config.total = sum(len(mutations) for mutations in mutations_by_file.values())

    print()
    print("2. Checking mutants")
    progress = Progress(
        total=config.total, output_legend=output_legend, no_progress=no_progress
    )

    if parallelize:
        tmpdirname = str(Path(".temp_dir").resolve())
        if not Path(tmpdirname).exists():
            os.mkdir(tmpdirname)
        temp_dir_storage.tmpdirname = tmpdirname
        copy_directory(str(project_path_storage.get_current_project_path()), tmpdirname)

    mutation_tests_runner = MutationTestsRunner()

    try:
        mutation_tests_runner.run_mutation_tests(
            config=config,
            progress=progress,
            mutations_by_file=mutations_by_file,
            project_path=project_path,
        )
    except Exception as e:
        traceback.print_exc()
        return compute_exit_code(progress, e)
    else:
        return compute_exit_code(progress, ci=ci)
    finally:
        print()  # make sure we end the output with a newline
        # Close all active multiprocessing queues to avoid hanging up the main process
        mutation_tests_runner.close_active_queues()


def parse_run_argument(
    argument: str | None,
    config: Config,
    dict_synonyms: SequenceStr,
    mutations_by_file: MutationsByFile,
    paths_to_exclude: SequenceStr,
    paths_to_mutate: SequenceStr,
    tests_dirs: SequenceStr,
) -> None:
    assert isinstance(mutations_by_file, dict)
    assert isinstance(tests_dirs, list)
    # argument is the mutation id or a path to a file to mutate
    if argument is None:
        for path in paths_to_mutate:
            # paths to mutate should be relative here
            assert not Path(path).is_absolute()
            print("Analizando path", str(Path(path)))
            with DirContext(project_path_storage.get_current_project_path()):
                for filename in python_source_files(
                    Path(path), tests_dirs, paths_to_exclude
                ):
                    if filename.startswith("test_") or filename.endswith("__tests.py"):
                        continue
                    update_line_numbers(filename)
                    add_mutations_by_file(
                        mutations_by_file, filename, dict_synonyms, config
                    )
    elif argument.isdigit():
        filename, mutation_id = filename_and_mutation_id_from_pk(int(argument))
        update_line_numbers(filename)
        mutations_by_file[filename] = [mutation_id]
    else:
        assert isinstance(argument, str)
        filename = FilenameStr(argument)
        if not os.path.exists(filename):
            raise click.BadArgumentUsage(
                "The run command takes either an integer that is the mutation id or a path to a file to mutate"
            )
        update_line_numbers(filename)
        add_mutations_by_file(mutations_by_file, filename, dict_synonyms, config)


def _get_tests_dirs(
    *, paths_to_mutate: SequenceStr, test_paths: list[str]
) -> list[str]:
    tests_dirs: list[str] = []

    with DirContext(
        project_path_storage.get_current_project_path()
    ):  # parece que es irrelevante # TODO: review
        for p in test_paths:
            tests_dirs.extend(glob(p, recursive=True))

        for p in paths_to_mutate:
            for pt in test_paths:
                assert pt is not None
                tests_dirs.extend(glob(p + "/**/" + pt, recursive=True))

    return tests_dirs


def time_test_suite(
    swallow_output: bool,
    test_command: str,
    using_testmon: bool,
    current_hash_of_tests: str,
    no_progress: bool,
) -> float:
    """Execute a test suite specified by ``test_command`` and record
    the time it took to execute the test suite as a floating point number

    :param swallow_output: if :obj:`True` test stdout will be not be printed
    :param test_command: command to spawn the testing subprocess
    :param using_testmon: if :obj:`True` the test return code evaluation will
        accommodate for ``pytest-testmon``

    :return: execution time of the test suite
    """
    cached_time = cached_test_time()
    if cached_time is not None and current_hash_of_tests == cached_hash_of_tests():
        print(
            "1. Using cached time for baseline tests, to run baseline again delete the cache file"
        )
        return cached_time

    print("1. Running tests without mutations")
    start_time = time()

    output: list[str] = []

    def feedback(line: str) -> None:
        if not swallow_output:
            print(line)
        if not no_progress:
            print_status("Running...")
        output.append(line)

    returncode = popen_streaming_output(test_command, feedback)

    if returncode == 0 or (using_testmon and returncode == 5):
        baseline_time_elapsed = time() - start_time
    else:
        logger.info(f"{os.getcwd()=}")
        raise RuntimeError(
            "Tests don't run cleanly without mutations. Test command was: {}\n\nOutput:\n\n{}".format(
                test_command, "\n".join(output)
            )
        )

    print("Done")

    set_cached_test_time(baseline_time_elapsed, current_hash_of_tests)

    return baseline_time_elapsed


def dict_synonyms_to_list(dict_synonyms: str) -> list[str]:
    return [x.strip() for x in dict_synonyms.split(",")]
