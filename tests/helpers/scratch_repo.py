"""Throwaway git repositories for tests that read history."""

from __future__ import annotations

import subprocess
from collections.abc import Mapping
from pathlib import Path


def git(repo: Path, *args: str) -> str:
    done = subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)
    return done.stdout.strip()


def write(repo: Path, relpath: str, text: str) -> None:
    path = repo / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def git_repo(tmp_path: Path, files: Mapping[str, str]) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "commit.gpgsign", "false")
    for relpath, text in files.items():
        write(repo, relpath, text)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "base")
    return repo
