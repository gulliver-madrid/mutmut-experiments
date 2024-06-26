#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import sys
from io import open
from pathlib import Path
from types import NoneType
from typing import List, NoReturn, cast

import click


# ensure mutmut modules are detected
base = Path(__file__).parent.parent
if str(base) not in sys.path:
    sys.path.insert(0, str(base))

from src.core import (
    __version__,
    config_from_file,
)
from src.cache.cache import (
    filename_and_mutation_id_from_pk,
    get_unified_diff,
)
from src.cache.update_line_numbers import update_line_numbers
from src.reporters import (
    create_html_report,
    print_result_cache,
    print_result_cache_junitxml,
    print_result_ids_cache,
)
from src.context import Context
from src.do_run import DEFAULT_RUNNER, do_run
from src.mutation_test_runner.run_mutation import mutate_file
from src.tools import configure_logger
from src.shared import POLICIES, PolicyStr
from src.status import MUTANT_STATUSES, StatusStr
from src.utils import SequenceStr, dict_synonyms_to_list
from src.storage import storage


logger = configure_logger(__name__)


add_project_option = click.option(
    "-p", "--project", help="base directory of the project", type=click.STRING
)
context_settings = dict(help_option_names=["-h", "--help"])


def do_apply(mutation_pk: str, dict_synonyms: SequenceStr, backup: bool) -> None:
    """Apply a specified mutant to the source code

    :param mutation_pk: mutmut cache primary key of the mutant to apply
    :param dict_synonyms: sequence of synonym keywords for a python dictionary
    :param backup: if :obj:`True` create a backup of the source file
        before applying the mutation
    """
    filename, mutation_id = filename_and_mutation_id_from_pk(mutation_pk)

    update_line_numbers(filename)

    context = Context(
        mutation_id=mutation_id,
        filename=filename,
        dict_synonyms=dict_synonyms,
    )
    mutate_file(
        backup=backup,
        context=context,
    )


null_out = open(os.devnull, "w")


@click.group(context_settings=context_settings)
def climain() -> None:
    """
    -----------------------------\n
    Ejecutando mutmut-experiments\n
    -----------------------------

    Mutation testing system for Python.

    Getting started:

    To run with pytest in test or tests folder: mutmut run

    For more options: mutmut run --help

    To show the results: mutmut results

    To generate HTML report: mutmut html
    """
    pass


@climain.command()
def version() -> NoReturn:
    """Show the version and exit."""
    print("mutmut-experiments (mutmut version {})".format(__version__))
    sys.exit(0)


@climain.command(context_settings=context_settings)
@click.argument("argument", nargs=1, required=False)
@click.option("--paths-to-mutate", type=click.STRING)
@click.option(
    "--disable-mutation-types",
    type=click.STRING,
    help="Skip the given types of mutations.",
)
@click.option(
    "--enable-mutation-types",
    type=click.STRING,
    help="Only perform given types of mutations.",
)
@click.option("--paths-to-exclude", type=click.STRING)
@click.option("--runner")
@click.option("--use-coverage", is_flag=True, default=False)
@click.option(
    "--use-patch-file", help="Only mutate lines added/changed in the given patch file"
)
@click.option(
    "--rerun-all",
    is_flag=True,
    default=False,
    help="If you modified the test_command in the pre_mutation hook, "
    'the default test_command (specified by the "runner" option) '
    "will be executed if the mutant survives with your modified test_command.",
)
@click.option("--tests-dir")
@click.option("-m", "--test-time-multiplier", default=2.0, type=float)
@click.option("-b", "--test-time-base", default=0.0, type=float)
@add_project_option
@click.option("-s", "--swallow-output", help="turn off output capture", is_flag=True)
@click.option("--parallelize", help="use parallelization", is_flag=True, default=False)
@click.option("--dict-synonyms")
@click.option("--pre-mutation")
@click.option("--post-mutation")
@click.option(
    "--simple-output",
    is_flag=True,
    default=False,
    help="Swap emojis in mutmut output to plain text alternatives.",
)
@click.option(
    "--no-progress",
    is_flag=True,
    default=False,
    help="Disable real-time progress indicator",
)
@click.option(
    "--CI",
    is_flag=True,
    default=False,
    help="Returns an exit code of 0 for all successful runs and an exit code of 1 for fatal errors.",
)
@config_from_file(
    dict_synonyms="",
    paths_to_exclude="",
    runner=DEFAULT_RUNNER,
    tests_dir="tests/:test/",
    pre_mutation=None,
    post_mutation=None,
    use_patch_file=None,
    parallelize=False,
)
def run(
    *,
    argument: str | None,
    paths_to_mutate: str | None,
    disable_mutation_types: str,
    enable_mutation_types: str,
    runner: str | None,
    tests_dir: str,  # TODO: check no other type is allowed in config file
    test_time_multiplier: float | None,
    test_time_base: float | None,
    swallow_output: bool | None,
    parallelize: bool,
    use_coverage: bool,
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
) -> NoReturn:
    """
    Runs mutmut. You probably want to start with just trying this. If you supply a mutation ID mutmut will check just this mutant.

    Runs pytest by default (or unittest if pytest is unavailable) on tests in the “tests” or “test” folder.

    It is recommended to configure any non-default options needed in setup.cfg or pyproject.toml, as described in the documentation.

    Exit codes:

     * 0 - all mutants were killed

    Otherwise any or sum of any of the following exit codes:

     * 1 - if a fatal error occurred

     * 2 - if one or more mutants survived

     * 4 - if one or more mutants timed out

     * 8 - if one or more mutants caused tests to take twice as long

    (This is equivalent to a bit-OR combination of the exit codes that may apply.)

    With --CI flag enabled, the exit code will always be
    1 for a fatal error or 0 for any other case.
    """
    assert isinstance(argument, (NoneType, str))
    assert isinstance(test_time_base, (float, NoneType))
    assert isinstance(test_time_multiplier, (float, NoneType))
    assert isinstance(simple_output, (bool, NoneType)), type(simple_output)
    assert isinstance(no_progress, (bool, NoneType)), type(no_progress)
    assert isinstance(ci, (bool, NoneType)), type(ci)
    assert isinstance(rerun_all, (bool, NoneType)), type(rerun_all)
    assert isinstance(dict_synonyms, str)
    assert isinstance(tests_dir, str), tests_dir
    assert isinstance(parallelize, bool), type(parallelize)

    if test_time_base is None:  # click sets the default=0.0 to None
        test_time_base = 0.0
    if test_time_multiplier is None:  # click sets the default=0.0 to None
        test_time_multiplier = 0.0

    sys.exit(
        do_run(
            argument,
            paths_to_mutate,
            disable_mutation_types,
            enable_mutation_types,
            runner,
            tests_dir,
            test_time_multiplier,
            test_time_base,
            swallow_output,
            use_coverage,
            dict_synonyms,
            pre_mutation,
            post_mutation,
            use_patch_file,
            paths_to_exclude,
            simple_output,
            no_progress,
            ci,
            rerun_all,
            project,
            parallelize,
        )
    )


@climain.command(context_settings=context_settings)
@add_project_option
def results(project: str | None) -> NoReturn:
    """
    Print the results.
    """
    assert isinstance(project, (str, NoneType))
    storage.project_path.set_project_path(project)
    if not storage.get_cache_path().exists():
        print("There is no results yet. Please run `mutmut run` first.\n")
        sys.exit(1)
    print_result_cache()
    sys.exit(0)


@climain.command(context_settings=context_settings)
@click.argument("status", nargs=1, required=True)
@add_project_option
def result_ids(status: str, project: str | None) -> NoReturn:
    """
    Print the IDs of the specified mutant classes (separated by spaces).\n
    result-ids survived (or any other of: killed,timeout,suspicious,skipped,untested)\n
    """
    if not status or status not in MUTANT_STATUSES:
        raise click.BadArgumentUsage(
            f"The result-ids command needs a status class of mutants "
            f"(one of : {set(MUTANT_STATUSES.keys())}) but was {status}"
        )
    storage.project_path.set_project_path(project)
    if not storage.get_cache_path().exists():
        print("There is no results yet. Please run `mutmut run` first.\n")
        sys.exit(1)
    status = cast(StatusStr, status)
    print_result_ids_cache(status)
    sys.exit(0)


@climain.command(context_settings=context_settings)
@click.argument("mutation-id", nargs=1, required=True)
@click.option("--backup/--no-backup", default=False)
@click.option("--dict-synonyms")
@add_project_option
@config_from_file(dict_synonyms="")
def apply(
    mutation_id: str, backup: bool, dict_synonyms: List[str], project: str | None
) -> NoReturn:
    """
    Apply a mutation on disk.
    """
    storage.project_path.set_project_path(project)
    if not storage.get_cache_path().exists():
        print("There is no mutants to apply yet. Please run `mutmut run` first.\n")
        sys.exit(1)
    do_apply(mutation_id, dict_synonyms, backup)
    sys.exit(0)


@climain.command(context_settings=context_settings)
@click.argument("id-or-file", nargs=1, required=False)
@click.option("--dict-synonyms")
@add_project_option
@config_from_file(dict_synonyms="")
def show(id_or_file: str | None, dict_synonyms: str, project: str | None) -> NoReturn:
    """
    Show a mutation diff.
    """
    assert isinstance(id_or_file, (str, NoneType)), id_or_file  # guess
    storage.project_path.set_project_path(project)
    if not storage.get_cache_path().exists():
        print("There is no results to show yet. Please run `mutmut run` first.\n")
        sys.exit(1)

    storage.project_path.set_project_path(project)

    dict_synonyms_as_list = dict_synonyms_to_list(dict_synonyms)
    if not id_or_file:
        print_result_cache()
        sys.exit(0)

    if id_or_file == "all":
        print_result_cache(show_diffs=True, dict_synonyms=dict_synonyms_as_list)
        sys.exit(0)

    if os.path.isfile(id_or_file):
        print_result_cache(
            show_diffs=True,
            only_this_file=id_or_file,
            dict_synonyms=dict_synonyms_as_list,
        )
        sys.exit(0)
    assert isinstance(id_or_file, str)
    print(get_unified_diff(id_or_file, dict_synonyms_as_list))
    sys.exit(0)


@climain.command(context_settings=context_settings)
@click.option("--dict-synonyms")
@click.option("--suspicious-policy", type=click.Choice(POLICIES), default="ignore")
@click.option("--untested-policy", type=click.Choice(POLICIES), default="ignore")
@add_project_option
@config_from_file(dict_synonyms="")
def junitxml(
    dict_synonyms: str,
    suspicious_policy: PolicyStr,
    untested_policy: PolicyStr,
    project: str | None,
) -> NoReturn:
    """
    Show a mutation diff with junitxml format.
    """
    assert isinstance(dict_synonyms, str)
    storage.project_path.set_project_path(project)
    if not storage.get_cache_path().exists():
        print("There is no results yet. Please run `mutmut run` first.\n")
        sys.exit(1)
    dict_synonyms_as_list = dict_synonyms_to_list(dict_synonyms)
    print_result_cache_junitxml(
        dict_synonyms_as_list, suspicious_policy, untested_policy
    )
    sys.exit(0)


@climain.command(context_settings=context_settings)
@click.option("--dict-synonyms")
@click.option("-d", "--directory", help="Write the output files to DIR.")
@add_project_option
@config_from_file(
    dict_synonyms="",
    directory="html",
)
def html(dict_synonyms: str, directory: str, project: str | None) -> NoReturn:
    """
    Generate a HTML report of surviving mutants.
    """
    storage.project_path.set_project_path(project)
    if not storage.get_cache_path().exists():
        print("There is no results yet. Please run `mutmut run` first.\n")
        sys.exit(1)
    dict_synonyms_as_list = dict_synonyms_to_list(dict_synonyms)
    create_html_report(dict_synonyms_as_list, directory)
    sys.exit(0)


if __name__ == "__main__":
    climain(prog_name="mut")
