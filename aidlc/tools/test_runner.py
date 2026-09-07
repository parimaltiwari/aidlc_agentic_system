"""Pytest subprocess runner."""

import subprocess
from pathlib import Path


def run_tests(path: str | Path) -> tuple[bool, str]:
    result = subprocess.run(["pytest", "-q"], cwd=path, capture_output=True, text=True, check=False)
    return result.returncode == 0, result.stdout + result.stderr
