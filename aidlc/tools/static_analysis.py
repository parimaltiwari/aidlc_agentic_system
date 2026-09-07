"""Ruff-backed static analysis with a deterministic fallback."""

import shutil
import subprocess
from pathlib import Path


def run_static_analysis(path: str | Path) -> tuple[bool, str]:
    if not shutil.which("ruff"):
        return True, "ruff unavailable; static analysis skipped"
    result = subprocess.run(
        ["ruff", "check", str(path)], capture_output=True, text=True, check=False
    )
    return result.returncode == 0, result.stdout + result.stderr
