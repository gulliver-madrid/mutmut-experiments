# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import shlex
import subprocess
from threading import Timer
from typing import Any, Callable, Optional



def popen_streaming_output(
    cmd: str, callback: Callable[[str], None], timeout: Optional[float] = None
) -> int:
    """Open a subprocess and stream its output without hard-blocking.

    :param cmd: the command to execute within the subprocess
    :param callback: function that intakes the subprocess' stdout line by line.
        It is called for each line received from the subprocess' stdout stream.
    :param timeout: the timeout time of the subprocess
    :raises TimeoutError: if the subprocess' execution time exceeds
        the timeout time
    :return: the return code of the executed subprocess
    """
    if os.name == 'nt':  # pragma: no cover
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            shell=True,
        )
        stdout = process.stdout
    else:
        master, slave = os.openpty()  # type: ignore [attr-defined]
        process = subprocess.Popen(
            shlex.split(cmd, posix=True),
            stdout=slave,
            stderr=slave
        )
        stdout = os.fdopen(master)  # type: ignore [assignment]
        os.close(slave)

    def kill(process_: Any) -> None:
        """Kill the specified process on Timer completion"""
        try:
            process_.kill()
        except OSError:
            pass

    # python 2-3 agnostic process timer
    timer = Timer(timeout, kill, [process])  # type: ignore [arg-type]
    timer.daemon = True
    timer.start()

    line: bytes | str
    while process.returncode is None:
        try:
            if os.name == 'nt':  # pragma: no cover
                assert stdout is not None
                line = stdout.readline()
                # windows gives readline() raw stdout as a b''
                # need to decode it
                line = line.decode("utf-8")
                if line:  # ignore empty strings and None
                    callback(line)
            else:
                while True:
                    assert stdout is not None
                    line = stdout.readline()
                    if not line:
                        break
                    callback(line)  # type: ignore [arg-type]
        except OSError:
            # This seems to happen on some platforms, including TravisCI.
            # It seems like it's ok to just let this pass here, you just
            # won't get as nice feedback.
            pass
        if not timer.is_alive():
            raise TimeoutError("subprocess running command '{}' timed out after {} seconds".format(cmd, timeout))
        process.poll()

    # we have returned from the subprocess cancel the timer if it is running
    timer.cancel()

    return process.returncode
