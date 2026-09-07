"""Pytest subprocess runner."""

import subprocess
import sys
from pathlib import Path


def run_tests(path: str | Path) -> tuple[bool, str]:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        cwd=path,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0, result.stdout + result.stderr
