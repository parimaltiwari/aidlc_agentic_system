"""Small local sandbox helper."""

import subprocess
from pathlib import Path


def run(command: list[str], cwd: str | Path) -> tuple[int, str]:
    proc = subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False)
    return proc.returncode, proc.stdout + proc.stderr
