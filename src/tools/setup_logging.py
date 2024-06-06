import atexit
import logging
import shutil
import threading
import time
from logging.handlers import MemoryHandler
from pathlib import Path
from pprint import pformat
from typing import Optional

BUFFER_SIZE = 20

KB = 1024
MB = KB * 1024


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
    logger.setLevel(level)

    # Create a specific FileHandler to write to a file
    base_path = get_main_directory() / "logs"

    # Maximum size of 1 MB per subdirectory
    log_dir = get_next_subdirectory(base_path, max_size_per_dir=10 * KB)

    file_handler = logging.FileHandler(log_dir / log_file_name, encoding="utf-8")
    file_handler.setLevel(level)

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


def get_next_subdirectory(
    base_path: Path, max_subdirs: int = 3, max_size_per_dir: int = 10 * MB
) -> Path:
    """
    Selects or creates the appropriate log subdirectory based on the total size of the log files.
    If all subdirectories are full, it deletes the oldest one and creates a new subdirectory with the next number.
    """
    subdirs = sorted(base_path.glob("logs_*"))
    for subdir in subdirs:
        total_size = sum(f.stat().st_size for f in subdir.glob("*.log") if f.is_file())
        if total_size < max_size_per_dir:
            return subdir

    # If all subdirectories are full, delete the oldest one and create a new subdirectory
    if len(subdirs) >= max_subdirs:
        oldest_subdir = subdirs[0]
        shutil.rmtree(oldest_subdir)
        subdirs = subdirs[1:]

    # Create a new subdirectory with the next number
    if subdirs:
        last_subdir_num = int(subdirs[-1].name.split("_")[-1])
        new_subdir_num = (last_subdir_num + 1) % 1000
    else:
        new_subdir_num = 0

    new_subdir = base_path / f"logs_{new_subdir_num:03d}"
    new_subdir.mkdir(parents=True)
    return new_subdir


def format_var(name: str, obj: object) -> str:
    return name + "=" + pformat(obj, width=120)
