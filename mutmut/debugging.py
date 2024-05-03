import inspect

PROJECT_DIRECTORY_NAME = "mutmut-experiments"
IGNORE = [".venv", "Users"]


def print_function_stack() -> None:
    # Gets the current call stack
    stack = inspect.stack()
    print("\nCall stack:")
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
        filepath_splitted = filepath.split(PROJECT_DIRECTORY_NAME)
        if len(filepath_splitted) == 1:
            file = filepath_splitted[0]
        else:
            file = "..." + filepath_splitted[1]
        print(f"File: {file}, Line: {info[1]}, Function: {info[2]}")
