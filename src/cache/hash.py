# -*- coding: utf-8 -*-


import hashlib
import os
from io import open


from src.shared import NO_TESTS_FOUND, FilenameStr, HashStr, HashResult
from src.storage import storage
from src.utils import SequenceStr


def hash_of(filename: FilenameStr) -> HashStr:
    with open(storage.project_path.get_current_project_path() / filename, "rb") as f:
        m = hashlib.sha256()
        m.update(f.read())
        return HashStr(m.hexdigest())


def get_hash_of_tests(tests_dirs: SequenceStr) -> HashResult:
    m = hashlib.sha256()
    found_something = False
    for tests_dir in tests_dirs:
        for root, _dirs, files in os.walk(tests_dir):
            for filename in files:
                if not filename.endswith(".py"):
                    continue
                if (
                    not filename.startswith("test")
                    and not filename.endswith("_tests.py")
                    and "test" not in root
                ):
                    continue
                with open(os.path.join(root, filename), "rb") as f:
                    m.update(f.read())
                    found_something = True
    if not found_something:
        return NO_TESTS_FOUND
    return HashStr(m.hexdigest())
