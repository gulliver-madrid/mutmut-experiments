import atexit
import logging
import threading
from logging.handlers import MemoryHandler
from pathlib import Path
from pprint import pformat
from typing import Optional


class CustomBufferingHandler(MemoryHandler):
    def __init__(
        self,
        capacity: int,
        flushLevel: int = logging.ERROR,
        *,
        target: Optional[logging.Handler] = None,
    ):
        super().__init__(capacity, flushLevel, target)

    def shouldFlush(self, record: logging.LogRecord) -> bool:
        return len(self.buffer) >= self.capacity


# Function to configure a logger and send its output to a file
def configure_logger(name: str, level: int = logging.DEBUG) -> logging.Logger:
    log_file_name = f"{name}.log"

    # Create a specific logger
    logger = logging.getLogger(name)
    logger.propagate = False  # Prevent propagation to the root logger
    logger.setLevel(level)  # Set the logger level

    # Create a specific FileHandler to write to a file
    path = get_main_directory() / "logs"
    if not path.exists():
        path.mkdir()
    file_handler = logging.FileHandler(path / log_file_name, encoding="utf-8")
    file_handler.setLevel(level)  # Set the FileHandler level

    # Create a formatter and add it to the FileHandler
    formatter = logging.Formatter(
        "%(asctime)s - %(levelname)s - %(name)s:%(lineno)d - %(message)s"
    )
    file_handler.setFormatter(formatter)

    # Add the handlers to the logger
    buffer_handler = CustomBufferingHandler(20, target=file_handler)
    buffer_handler.setLevel(level)
    logger.addHandler(buffer_handler)

    logger.info("\n")
    logger.info(f"START (thread id={threading.get_ident()})")

    atexit.register(buffer_handler.flush)

    return logger


def get_main_directory() -> Path:
    return Path(__file__).parents[2]


def format_var(name: str, obj: object) -> str:
    return name + "=" + pformat(obj, width=120)
