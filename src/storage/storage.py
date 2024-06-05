from pathlib import Path
from typing import Final

from .dynamic_config_storage import UserDynamicConfigStorage
from .project import ProjectPathStorage, TempDirectoryStorage


class Storage:
    def __init__(self) -> None:
        self.project_path: Final = ProjectPathStorage()
        self.temp_dir: Final = TempDirectoryStorage()
        self.dynamic_config: Final = UserDynamicConfigStorage(self.project_path)

    def get_cache_path(self) -> Path:
        cache_path = self._get_cache_path()
        # print(f"{cache_path=}")
        return cache_path

    def _get_cache_path(self) -> Path:
        return self.project_path.get_current_project_path() / ".mutmut-cache"


def reset_global_vars() -> None:
    storage.dynamic_config.clear_cache()
    storage.project_path.reset()
    storage.temp_dir.reset()


# global variable
storage = Storage()
