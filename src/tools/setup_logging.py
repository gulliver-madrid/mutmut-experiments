import atexit
import logging
import threading
import time
from logging.handlers import MemoryHandler
from pathlib import Path
from pprint import pformat
from typing import Optional

BUFFER_SIZE = 20


class CustomFormatter(logging.Formatter):
    def formatTime(
        self, record: logging.LogRecord, datefmt: Optional[str] = None
    ) -> str:
        # Split date and time
        created_time = self.converter(record.created)
        return time.strftime("%H:%M:%S", created_time) + f",{int(record.msecs):03d}"

    def format(self, record: logging.LogRecord) -> str:
        record.asctime = self.formatTime(record)
        formatted = super().format(record)
        if record.message.startswith("\n"):
            formatted = "\n" + formatted[1:]
        return formatted


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
    formatter = CustomFormatter(
        "%(asctime)s - %(thread)d - %(levelname)s - %(name)s:%(lineno)d - %(message)s"
    )
    file_handler.setFormatter(formatter)

    # Add the handlers to the logger
    buffer_handler = CustomBufferingHandler(BUFFER_SIZE, target=file_handler)
    buffer_handler.setLevel(level)
    logger.addHandler(buffer_handler)

    created = time.time()
    created_time = time.localtime(created)
    date_str = time.strftime("%Y-%m-%d", created_time)
    logger.info(f"\nSTART (thread id={threading.get_ident()}, date={date_str})")

    atexit.register(buffer_handler.flush)

    return logger


def get_main_directory() -> Path:
    return Path(__file__).parents[2]


def format_var(name: str, obj: object) -> str:
    return name + "=" + pformat(obj, width=120)
