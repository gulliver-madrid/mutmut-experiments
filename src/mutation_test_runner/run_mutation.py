# -*- coding: utf-8 -*-
import os
from pathlib import Path
import subprocess
from io import open
from shutil import move
from time import time
from typing import Tuple

from src.config import Config
from src.context import Context
from src.dir_context import DirContext
from src.mutate import mutate_from_context
from src.mutations import SkipException
from src.setup_logging import configure_logger
from src.status import (
    BAD_SURVIVED,
    BAD_TIMEOUT,
    OK_KILLED,
    OK_SUSPICIOUS,
    SKIPPED,
    UNTESTED,
    StatusResultStr,
)
from src.storage import storage

from .constants import NUMBER_OF_PROCESSES_IN_PARALLELIZATION_MODE
from .test_runner import StrConsumer, TestRunner

logger = configure_logger(__name__)


def run_mutation(
    context: Context,
    callback: StrConsumer,
    *,
    mutation_project_path: Path,
) -> StatusResultStr:
    """
    :return: (computed or cached) status of the tested mutant, one of mutant_statuses
    """
    from src.cache.cache import cached_mutation_status

    assert context.config is not None
    assert context.filename is not None

    logger.info(f"{context.mutation_id=}")

    with DirContext(mutation_project_path):

        dynamic_config = storage.dynamic_config.get_dynamic_config()
        cached_status = cached_mutation_status(
            context.filename, context.mutation_id, context.config.hash_of_tests
        )

        if cached_status != UNTESTED and context.config.total != 1:
            return cached_status  # pyright: ignore

        config = context.config
        if dynamic_config is not None and hasattr(dynamic_config, "pre_mutation"):
            context.current_line_index = context.mutation_id.line_number
            try:
                dynamic_config.pre_mutation(context=context)
            except SkipException:
                return SKIPPED
            if context.skip:
                return SKIPPED

        if config.dynamic.pre_mutation:
            _execute_dynamic_function(config.dynamic.pre_mutation, config, callback)

        test_runner = TestRunner()

        try:
            mutate_file(backup=True, context=context, subdir=Path(os.getcwd()))
            start = time()
            try:
                survived = test_runner.tests_pass(config=config, callback=callback)
                if _should_rerun(survived, config):
                    # rerun the whole test suite to be sure the mutant can not be killed by other tests
                    config.test_command = config.default_test_command
                    survived = test_runner.tests_pass(config=config, callback=callback)
            except TimeoutError:
                return BAD_TIMEOUT

            time_elapsed = time() - start
            time_expected = _get_time_expected(config)
            if not survived and time_elapsed > time_expected:
                return OK_SUSPICIOUS

            if survived:
                return BAD_SURVIVED
            else:
                return OK_KILLED
        except SkipException:
            return SKIPPED

        finally:
            assert isinstance(context.filename, str)
            move(context.filename + ".bak", context.filename)

            config.test_command = (
                config.default_test_command
            )  # reset test command to its default in the case it was altered in a hook
            if config.dynamic.post_mutation:
                _execute_dynamic_function(
                    config.dynamic.post_mutation, config, callback
                )


def mutate_file(
    backup: bool, context: Context, *, subdir: Path | None = None
) -> Tuple[str, str]:
    assert isinstance(context.filename, str)
    # directory to apply mutations
    mutation_project_path = Path(
        storage.temp_dir.tmpdirname or storage.project_path.get_current_project_path()
    )

    if subdir:
        mutation_project_path /= subdir
    with DirContext(mutation_project_path):
        with open(context.filename) as f:
            original = f.read()
        if backup:
            with open(context.filename + ".bak", "w") as f:
                f.write(original)
        mutated, _ = mutate_from_context(context)
        with open(context.filename, "w") as f:
            f.write(mutated)
        return original, mutated


def _should_rerun(survived: bool, config: Config) -> bool:
    return (
        survived
        and config.test_command != config.default_test_command
        and config.flags.rerun_all
    )


def _get_time_expected(config: Config) -> float:
    cfg = config.test_time
    time_expected = cfg.test_time_base + (
        cfg.baseline_time_elapsed * cfg.test_time_multiplier
    )
    if config.flags.parallelize:
        time_expected *= NUMBER_OF_PROCESSES_IN_PARALLELIZATION_MODE
    return time_expected


def _execute_dynamic_function(
    function_name: str, config: Config, callback: StrConsumer
) -> None:
    result = subprocess.check_output(function_name, shell=True).decode().strip()
    if result and not config.flags.swallow_output:
        callback(result)
