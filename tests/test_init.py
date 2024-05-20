import os
from pathlib import Path
from time import sleep
from typing import Any, Literal, cast
from pytest import raises, fixture
from unittest.mock import MagicMock, patch

from src import (
    MutationTestsRunner,
    check_mutants,
)
from src.config import Config
from src.context import Context
from src.mutate import mutate_from_context
from src.mutations import partition_node_list, name_mutation
from src.patch import read_patch_data
from src.setup_logging import configure_logger
from src.status import OK_KILLED

logger = configure_logger(__name__)


def test_partition_node_list_no_nodes() -> None:
    with raises(AssertionError):
        partition_node_list([], None)


def test_name_mutation_simple_mutants() -> None:
    assert name_mutation(node=None, value="True") == "False"


def test_context_exclude_line() -> None:
    source = "__import__('pkg_resources').declare_namespace(__name__)\n"
    assert mutate_from_context(Context(source=source)) == (source, 0)

    source = "__all__ = ['hi']\n"
    assert mutate_from_context(Context(source=source)) == (source, 0)


def check_mutants_stub(**kwargs: Any) -> None:
    def run_mutation_stub(*_: object) -> Literal["ok_killed"]:
        sleep(0.15)
        return OK_KILLED

    check_mutants_original = check_mutants
    with patch("src.run_mutation", run_mutation_stub):
        check_mutants_original(**kwargs)


class ConfigStub:
    hash_of_tests = None


config_stub = cast(Config, ConfigStub())


def test_run_mutation_tests_thread_synchronization(monkeypatch: Any) -> None:
    # arrange
    total_mutants = 3
    cycle_process_after = 1

    def queue_mutants_stub(**kwargs: Any) -> None:
        for _ in range(total_mutants):
            kwargs["mutants_queue"].put(("mutant", Context(config=config_stub)))
        kwargs["mutants_queue"].put(("end", None))

    monkeypatch.setattr("src.queue_mutants", queue_mutants_stub)

    def update_mutant_status_stub(**_: Any) -> None:
        sleep(0.1)

    monkeypatch.setattr("src.check_mutants", check_mutants_stub)
    monkeypatch.setattr(
        "src.cache.cache.update_mutant_status", update_mutant_status_stub
    )
    monkeypatch.setattr("src.CYCLE_PROCESS_AFTER", cycle_process_after)

    progress_mock = MagicMock()
    progress_mock.registered_mutants = 0

    def progress_mock_register(*_: Any) -> None:
        progress_mock.registered_mutants += 1

    progress_mock.register = progress_mock_register

    # act
    mutation_tests_runner = MutationTestsRunner()
    mutation_tests_runner.run_mutation_tests(config_stub, progress_mock, None)

    # assert
    assert progress_mock.registered_mutants == total_mutants

    mutation_tests_runner.close_active_queues()


@fixture
def testpatches_path(testdata: Path) -> Path:
    return testdata / "test_patches"


def test_read_patch_data_new_empty_file_not_in_the_list(testpatches_path: Path) -> None:
    # arrange
    new_empty_file_name = "new_empty_file.txt"
    new_empty_file_patch = testpatches_path / "add_empty_file.patch"

    # act
    new_empty_file_changes = read_patch_data(new_empty_file_patch)

    # assert
    assert not new_empty_file_name in new_empty_file_changes


def test_read_patch_data_removed_empty_file_not_in_the_list(
    testpatches_path: Path,
) -> None:
    # arrange
    existing_empty_file_name = "existing_empty_file.txt"
    remove_empty_file_patch = testpatches_path / "remove_empty_file.patch"

    # act
    remove_empty_file_changes = read_patch_data(remove_empty_file_patch)

    # assert
    assert existing_empty_file_name not in remove_empty_file_changes


def test_read_patch_data_renamed_empty_file_not_in_the_list(
    testpatches_path: Path,
) -> None:
    # arrange
    renamed_empty_file_name = "renamed_existing_empty_file.txt"
    renamed_empty_file_patch = testpatches_path / "renamed_empty_file.patch"

    # act
    renamed_empty_file_changes = read_patch_data(renamed_empty_file_patch)

    # assert
    assert renamed_empty_file_name not in renamed_empty_file_changes


def test_read_patch_data_added_line_is_in_the_list(testpatches_path: Path) -> None:
    # arrange
    file_name = "existing_file.txt"
    file_patch = testpatches_path / "add_new_line.patch"

    # act
    file_changes = read_patch_data(file_patch)

    # assert
    assert file_name in file_changes
    assert file_changes[file_name] == [3]  # line is added between second and third


def test_read_patch_data_edited_line_is_in_the_list(testpatches_path: Path) -> None:
    # arrange
    file_name = "existing_file.txt"
    file_patch = testpatches_path / "edit_existing_line.patch"

    # act
    file_changes = read_patch_data(file_patch)

    # assert
    assert file_name in file_changes
    assert file_changes[file_name] == [2]  # line is added between 2nd and 3rd


def test_read_patch_data_edited_line_in_subfolder_is_in_the_list(
    testpatches_path: Path,
) -> None:
    # arrange
    file_name = os.path.join(
        "sub", "existing_file.txt"
    )  # unix will use "/", windows "\" to join
    file_patch = testpatches_path / "edit_existing_line_in_subfolder.patch"

    # act
    file_changes = read_patch_data(file_patch)

    # assert
    assert file_name in file_changes
    assert file_changes[file_name] == [2]  # line is added between 2nd and 3rd


def test_read_patch_data_renamed_file_edited_line_is_in_the_list(
    testpatches_path: Path,
) -> None:
    # arrange
    original_file_name = "existing_file.txt"
    new_file_name = "renamed_existing_file.txt"
    file_patch = testpatches_path / "edit_existing_renamed_file_line.patch"

    # act
    file_changes = read_patch_data(file_patch)

    # assert
    assert original_file_name not in file_changes
    assert new_file_name in file_changes
    assert file_changes[new_file_name] == [3]  # 3rd line is edited


def test_read_patch_data_mutliple_files(testpatches_path: Path) -> None:
    # arrange
    expected_changes = {
        "existing_file.txt": [2, 3],
        "existing_file_2.txt": [4, 5],
        "new_file.txt": [1, 2, 3],
    }
    file_patch = testpatches_path / "multiple_files.patch"

    # act
    actual_changes = read_patch_data(file_patch)

    # assert
    assert actual_changes == expected_changes
