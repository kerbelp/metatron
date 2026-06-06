"""Shared fixtures, including a tiny real git repo builder."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


class GitRepoBuilder:
    """Builds a throwaway git repo for tests by making real commits."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._run("git", "init", "-q")
        self._run("git", "config", "user.email", "test@example.com")
        self._run("git", "config", "user.name", "Test")

    def _run(self, *args: str) -> str:
        return subprocess.run(
            args,
            cwd=self.path,
            check=True,
            capture_output=True,
            text=True,
        ).stdout

    def commit(self, message: str, files: dict[str, str]) -> str:
        for rel, content in files.items():
            target = self.path / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
            self._run("git", "add", rel)
        self._run("git", "commit", "-q", "-m", message)
        return self._run("git", "rev-parse", "HEAD").strip()


@pytest.fixture
def git_repo(tmp_path) -> GitRepoBuilder:
    return GitRepoBuilder(tmp_path)


@pytest.fixture(autouse=True)
def _isolate_metatron_store(tmp_path_factory, monkeypatch):
    """Keep every test off real paths.

    ``cli.main()`` builds the catalog from ``settings.db_path`` (default
    ``~/.metatron``) and runs the legacy-``metatron.db`` auto-split against the cwd.
    Without isolation a test could create/modify the developer's real catalog or
    migrate the repo's own ``metatron.db``. This points the catalog at a throwaway
    dir and parks the cwd in an empty one; tests that set their own ``METATRON_DB``
    or ``chdir`` later still override these.
    """
    home = tmp_path_factory.mktemp("metatron-home")
    monkeypatch.setenv("METATRON_DB", str(home / "catalog"))
    monkeypatch.delenv("METATRON_REPO", raising=False)
    monkeypatch.chdir(home)
