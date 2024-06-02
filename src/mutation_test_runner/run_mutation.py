# -*- coding: utf-8 -*-
import os
from pathlib import Path
import subprocess
from io import open
from shutil import move
from time import time
from typing import (
    Tuple,
)

from src.context import Context
from src.dir_context import DirContext
from src.dynamic_config_storage import user_dynamic_config_storage
from src.mutate import mutate_from_context
from src.project import project_path_storage, temp_dir_storage
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

        dynamic_config = user_dynamic_config_storage.get_dynamic_config()
        cached_status = cached_mutation_status(
            context.filename, context.mutation_id, context.config.hash_of_tests
        )

        if cached_status != UNTESTED and context.config.total != 1:
            return cached_status

        config = context.config
        if dynamic_config is not None and hasattr(dynamic_config, "pre_mutation"):
            context.current_line_index = context.mutation_id.line_number
            try:
                dynamic_config.pre_mutation(context=context)
            except SkipException:
                return SKIPPED
            if context.skip:
                return SKIPPED

        if config.pre_mutation:
            result = (
                subprocess.check_output(config.pre_mutation, shell=True)
                .decode()
                .strip()
            )
            if result and not config.swallow_output:
                callback(result)

        test_runner = TestRunner()

        try:
            mutate_file(backup=True, context=context, subdir=Path(os.getcwd()))
            start = time()
            try:
                survived = test_runner.tests_pass(config=config, callback=callback)
                if (
                    survived
                    and config.test_command != config.default_test_command
                    and config.rerun_all
                ):
                    # rerun the whole test suite to be sure the mutant can not be killed by other tests
                    config.test_command = config.default_test_command
                    survived = test_runner.tests_pass(config=config, callback=callback)
            except TimeoutError:
                return BAD_TIMEOUT

            time_elapsed = time() - start
            if not survived and time_elapsed > config.test_time_base + (
                config.baseline_time_elapsed * config.test_time_multiplier
            ):
                return OK_SUSPICIOUS

            if survived:
                return BAD_SURVIVED
            else:
                return OK_KILLED
        except SkipException:
            return SKIPPED

        finally:
            assert isinstance(context.filename, str)
            print(f"{context.filename=}")
            print("before:", os.getcwd())
            move(context.filename + ".bak", context.filename)
            print("after:", os.getcwd())

            config.test_command = (
                config.default_test_command
            )  # reset test command to its default in the case it was altered in a hook
            if config.post_mutation:
                result = (
                    subprocess.check_output(config.post_mutation, shell=True)
                    .decode()
                    .strip()
                )
                if result and not config.swallow_output:
                    callback(result)


def mutate_file(
    backup: bool, context: Context, *, subdir: Path | None = None
) -> Tuple[str, str]:
    assert isinstance(context.filename, str)
    # directory to apply mutations
    mutation_project_path = Path(
        temp_dir_storage.tmpdirname or project_path_storage.get_current_project_path()
    )

    if subdir:
        mutation_project_path /= subdir
    with DirContext(mutation_project_path):
        with open(context.filename) as f:
            original = f.read()
        print("Mutando archivo")
        print(f"{os.getcwd()=}")
        if backup:
            with open(context.filename + ".bak", "w") as f:
                print(f"{(context.filename + '.bak')=}")
                f.write(original)
        mutated, _ = mutate_from_context(context)
        with open(context.filename, "w") as f:
            f.write(mutated)
        return original, mutated
