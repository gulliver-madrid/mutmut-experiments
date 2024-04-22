import logging
from pathlib import Path
from pprint import pformat


# Function to configure a logger and send its output to a file
def configure_logger(name: str, level: int = logging.DEBUG) -> logging.Logger:
    log_file_name = f"{name}.log"

    # Create a specific logger
    logger = logging.getLogger(name)
    logger.propagate = False  # Prevent propagation to the root logger
    logger.setLevel(level)  # Set the logger level

    # Create a specific FileHandler to write to a file
    path = _get_main_directory() / "logs"
    if not path.exists():
        path.mkdir()
    file_handler = logging.FileHandler(path / log_file_name, encoding="utf-8")
    file_handler.setLevel(level)  # Set the FileHandler level

    # Create a formatter and add it to the FileHandler
    formatter = logging.Formatter(
        "%(asctime)s - %(levelname)s - %(name)s:%(lineno)d - %(message)s"
    )
    file_handler.setFormatter(formatter)

    # Add the FileHandler to the logger
    logger.addHandler(file_handler)
    logger.info("\n")
    logger.info("START")

    return logger


def _get_main_directory() -> Path:
    return Path(__file__).parents[1]


def format_var(name: str, obj: object) -> str:
    return name + "=" + pformat(obj, width=120)
