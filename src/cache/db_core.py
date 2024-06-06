# -*- coding: utf-8 -*-

from functools import wraps
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    ContextManager,
    TypeVar,
)

from pony.orm import RowNotFound, ERDiagramError, OperationalError
from typing_extensions import ParamSpec

from src.tools import configure_logger
from src.storage import storage

from .model import (
    MiscData,
    db,
    get_or_create,
)

logger = configure_logger(__name__)


current_db_version = 4

# Used for db_session and init_db
P = ParamSpec("P")
T = TypeVar("T")

if TYPE_CHECKING:

    def db_session(f: Callable[P, T]) -> Callable[P, T]: ...

    db_session_ctx_manager: ContextManager[Any]
else:
    from pony.orm import db_session

    db_session_ctx_manager = db_session


def init_db(f: Callable[P, T]) -> Callable[P, T]:
    @wraps(f)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
        if db.provider is None:
            cache_path = storage.get_cache_path()
            logger.info(
                f"El directorio donde se guarda la .mutmut-cache es {storage.project_path.get_current_project_path()}"
            )
            db.bind(provider="sqlite", filename=str(cache_path), create_db=True)

            try:
                db.generate_mapping(create_tables=True)
            except OperationalError:
                pass

            if cache_path.exists():
                # If the existing cache file is out of date, delete it and start over
                with db_session_ctx_manager:  # pyright: ignore
                    try:
                        v = MiscData.get(key="version")
                        if v is None:
                            existing_db_version = 1
                        else:
                            assert v.value is not None
                            existing_db_version = int(v.value)
                    except (RowNotFound, ERDiagramError, OperationalError):
                        existing_db_version = 1

                if existing_db_version != current_db_version:
                    print("mutmut cache is out of date, clearing it...")
                    db.drop_all_tables(with_all_data=True)
                    db.schema = (
                        None  # Pony otherwise thinks we've already created the tables
                    )
                    db.generate_mapping(create_tables=True)

            with db_session_ctx_manager:  # pyright: ignore
                v = get_or_create(MiscData, key="version")
                v.value = str(current_db_version)

        return f(*args, **kwargs)

    return wrapper
