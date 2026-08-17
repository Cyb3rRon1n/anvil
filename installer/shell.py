"""
Small shared subprocess helpers. run_ok() is a quiet "did this
succeed" check (used by detection); run_privileged() is for commands
that need root and deliberately does NOT capture output - sudo's
password prompt and an install script's own progress need to reach
the real terminal, unlike every quiet check in detect.py.

run_streaming() is the live-progress variant: when a stream sink is
set (see set_stream_sink()), run_privileged() tees each output line to
that sink (a Rich Live panel in the CLI front end) instead of the
terminal, while still returning the exact same result shapes - so
every caller keeps working unchanged whether or not a progress panel
is active.
"""

import os
import shutil
import subprocess

# The active line-by-line output sink, or None for plain pass-through.
# Never set outside a CLI progress panel's lifetime - see panel.py.
_stream_sink = None


def set_stream_sink(sink) -> None:

    global _stream_sink
    _stream_sink = sink


def get_stream_sink():

    return _stream_sink


def clear_stream_sink() -> None:

    global _stream_sink
    _stream_sink = None


def run_ok(command: list[str], timeout: int = 10) -> bool:

    try:

        result = subprocess.run(
            command,
            capture_output=True,
            timeout=timeout
        )

        return result.returncode == 0

    except (subprocess.SubprocessError, OSError):
        return False


def run_streaming(command: list[str], on_line) -> int:
    """
    Run a command with its stdout+stderr merged into a single stream,
    invoking on_line(line) for each newline-terminated chunk as it
    arrives. stdin is inherited so sudo's /dev/tty password prompt still
    reaches the real terminal. Returns the process's real exit code -
    never raises, an OSError (command not found, etc.) is surfaced as
    the nonzero exit code this function returns instead.
    """

    try:
        proc = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )

    except OSError:
        return 127

    assert proc.stdout is not None

    for line in proc.stdout:
        on_line(line.rstrip("\n"))

    proc.wait()
    return proc.returncode


def run_privileged(command: list[str]) -> dict:

    if os.geteuid() != 0:

        if not shutil.which("sudo"):

            return {
                "success": False,
                "error": "sudo not found and not running as root"
            }

        command = ["sudo", *command]

    sink = get_stream_sink()

    if sink is not None:

        returncode = run_streaming(command, sink)

        return {
            "success": returncode == 0,
            "error": None if returncode == 0 else f"exit code {returncode}"
        }

    try:
        result = subprocess.run(command)

    except OSError as error:

        return {
            "success": False,
            "error": str(error)
        }

    return {
        "success": result.returncode == 0,
        "error": None if result.returncode == 0 else f"exit code {result.returncode}"
    }
