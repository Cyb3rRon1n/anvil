"""
Small shared subprocess helpers. run_ok() is a quiet "did this
succeed" check (used by detection); run_privileged() is for commands
that need root and deliberately does NOT capture output - sudo's
password prompt and an install script's own progress need to reach
the real terminal, unlike every quiet check in detect.py.
"""

import os
import shutil
import subprocess


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


def run_privileged(command: list[str]) -> dict:

    if os.geteuid() != 0:

        if not shutil.which("sudo"):

            return {
                "success": False,
                "error": "sudo not found and not running as root"
            }

        command = ["sudo", *command]

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
