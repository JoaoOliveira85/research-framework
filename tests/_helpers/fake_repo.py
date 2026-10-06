"""Disposable git checkout helper (spec 020 SC-004)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

_GIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "test",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "test",
    "GIT_COMMITTER_EMAIL": "test@example.com",
}


class FakeRepo:
    """Minimal git repo with a controlled HEAD SHA."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._init()

    def _init(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init"], cwd=self.root, check=True, capture_output=True)
        (self.root / "README.md").write_text("fake\n", encoding="utf-8")
        subprocess.run(
            ["git", "add", "README.md"], cwd=self.root, check=True, capture_output=True
        )
        subprocess.run(
            ["git", "commit", "-m", "init", "--author", "test <test@example.com>"],
            cwd=self.root,
            check=True,
            capture_output=True,
            env={
                **os.environ,
                **_GIT_IDENTITY,
                "GIT_AUTHOR_DATE": "2020-01-01T00:00:00",
                "GIT_COMMITTER_DATE": "2020-01-01T00:00:00",
            },
        )

    def head_sha(self) -> str:
        proc = subprocess.run(
            ["git", "-C", str(self.root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        return proc.stdout.strip()

    def amend_readme(self, text: str) -> str:
        (self.root / "README.md").write_text(text, encoding="utf-8")
        subprocess.run(
            ["git", "add", "README.md"], cwd=self.root, check=True, capture_output=True
        )
        subprocess.run(
            ["git", "commit", "-m", "update", "--author", "test <test@example.com>"],
            cwd=self.root,
            check=True,
            capture_output=True,
            env={
                **os.environ,
                **_GIT_IDENTITY,
                "GIT_AUTHOR_DATE": "2020-01-02T00:00:00",
                "GIT_COMMITTER_DATE": "2020-01-02T00:00:00",
            },
        )
        return self.head_sha()
