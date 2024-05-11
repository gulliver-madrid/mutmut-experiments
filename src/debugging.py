import inspect
from typing import Callable

from src.setup_logging import configure_logger

PROJECT_DIRECTORY_NAME = "mutmut-experiments"
IGNORE = [".venv", "Users"]

logger = configure_logger(__name__)


def print_function_stack(max_deep: int = 3, log: Callable[[str], None] = logger.info) -> None:
    # Gets the current call stack
    stack = inspect.stack()
    log("\nCall stack:")
    for frame in stack[1:max_deep + 1]:  # start with the caller
        # Relevant information in each stack frame
        info = frame.filename, frame.lineno, frame.function
        filepath = info[0]
        skip = False
        for pattern in IGNORE:
            if pattern in filepath:
                skip = True
                break
        if skip:
            continue
        filepath_splitted = filepath.split(PROJECT_DIRECTORY_NAME)
        if len(filepath_splitted) == 1:
            file = filepath_splitted[0]
        else:
            file = "..." + filepath_splitted[1]
        log(f"File: {file}, Line: {info[1]}, Function: {info[2]}")
