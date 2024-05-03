import inspect

from .setup_logging import configure_logger, get_main_directory


logger = configure_logger(__name__)


IGNORE = [".venv", "Users"]


def log_function_stack() -> None:
    main_directory = get_main_directory()
    # Gets the current call stack
    stack = inspect.stack()
    content: list[str] = []
    content.append("\nCall stack:")
    for frame in stack:
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
        assert filepath.startswith(str(main_directory))
        filepath_relative = filepath[len(str(main_directory)) :]

        file = "..." + filepath_relative
        content.append(f"File: {file}, Line: {info[1]}, Function: {info[2]}")
    content.append("")
    logger.info("\n".join(content))
