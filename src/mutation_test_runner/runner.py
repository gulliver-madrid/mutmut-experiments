# -*- coding: utf-8 -*-
import os
import shlex
import shutil
import sys
from io import TextIOBase
from typing import (
    Callable,
    Final,
)

from src.config import Config
from src.process import popen_streaming_output

StrConsumer = Callable[[str], None]

hammett_prefix: Final = "python -m hammett "


class Runner:
    def do_tests_pass(self, config: Config, callback: StrConsumer) -> bool:
        """
        :return: :obj:`True` if the tests pass, otherwise :obj:`False`
        """
        if config.flags.using_testmon:
            shutil.copy(".testmondata-initial", ".testmondata")

        use_special_case = True

        # Special case for hammett! We can do in-process test running which is much faster
        if use_special_case and config.test_command.startswith(hammett_prefix):
            return self._hammett_tests_pass(config, callback)

        returncode = popen_streaming_output(
            config.test_command,
            callback,
            timeout=config.test_time.baseline_time_elapsed * 10,
        )
        return returncode != 1

    def _hammett_tests_pass(self, config: Config, callback: StrConsumer) -> bool:
        # noinspection PyUnresolvedReferences
        from hammett import main_cli  # type: ignore [import-untyped]

        modules_before = set(sys.modules.keys())

        # set up timeout
        import _thread
        from threading import (
            Timer,
            current_thread,
            main_thread,
        )

        timed_out = False

        def timeout() -> None:
            _thread.interrupt_main()
            nonlocal timed_out
            timed_out = True

        assert current_thread() is main_thread()
        timer = Timer(config.test_time.baseline_time_elapsed * 10, timeout)
        timer.daemon = True
        timer.start()

        # Run tests
        try:

            class StdOutRedirect(TextIOBase):
                def write(self, s: str) -> int:
                    callback(s)
                    return len(s)

            redirect = StdOutRedirect()
            sys.stdout = redirect  # type: ignore [assignment]
            sys.stderr = redirect  # type: ignore [assignment]
            returncode = main_cli(
                shlex.split(config.test_command[len(hammett_prefix) :])
            )
            sys.stdout = sys.__stdout__
            sys.stderr = sys.__stderr__
            timer.cancel()
        except KeyboardInterrupt:
            timer.cancel()
            if timed_out:
                raise TimeoutError("In process tests timed out")
            raise

        modules_to_force_unload = {
            x.partition(os.sep)[0].replace(".py", "") for x in config.paths_to_mutate
        }

        for module_name in sorted(
            set(sys.modules.keys()) - set(modules_before), reverse=True
        ):
            if (
                any(module_name.startswith(x) for x in modules_to_force_unload)
                or module_name.startswith("tests")
                or module_name.startswith("django")
            ):
                del sys.modules[module_name]

        return bool(returncode == 0)
