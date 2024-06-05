from typing import Final, Literal, NewType

FilenameStr = NewType("FilenameStr", str)

POLICIES: Final = ["ignore", "skipped", "error", "failure"]
PolicyStr = Literal["ignore", "skipped", "error", "failure"]

HashStr = NewType("HashStr", str)

NO_TESTS_FOUND: Final = "NO TESTS FOUND"

NoTestFoundSentinel = Literal["NO TESTS FOUND"]
HashResult = HashStr | NoTestFoundSentinel
