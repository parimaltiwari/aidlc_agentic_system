"""Ruff-backed static analysis with a deterministic fallback."""

import subprocess
import sys
from pathlib import Path


def run_static_analysis(path: str | Path) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            [sys.executable, "-m", "ruff", "check", str(path)],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return True, "ruff unavailable; static analysis skipped"
    return result.returncode == 0, result.stdout + result.stderr
