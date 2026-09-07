"""Safe git operations for sandbox copies."""

import shutil
import subprocess
from pathlib import Path


def copy_repo(repo_path: str, destination: str) -> Path:
    target = Path(destination)
    shutil.copytree(repo_path, target, dirs_exist_ok=True, ignore=shutil.ignore_patterns(".git"))
    return target


def commit(repo_path: str, message: str) -> str:
    subprocess.run(
        ["git", "init", "-b", "aidlc"], cwd=repo_path, check=True, capture_output=True, text=True
    )
    subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "commit", "-m", message], cwd=repo_path, check=True, capture_output=True, text=True
    )
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo_path, text=True).strip()
