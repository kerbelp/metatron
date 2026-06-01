"""Report the code revision being served.

The curation UI shows this so you can tell which commit a running server is on —
servers load the code once at startup and do not hot-reload, so "which version is
this?" is a real question. Resolved from git at the package location, with a plain
fallback when git/the repo is unavailable (e.g. an installed wheel).
"""

from __future__ import annotations

import subprocess
from functools import lru_cache
from pathlib import Path


def git_revision(repo_root: Path | str | None = None) -> str | None:
    """Short commit hash for ``repo_root`` (defaults to this package), or None."""
    root = Path(repo_root) if repo_root is not None else Path(__file__).resolve().parent
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def version_string(repo_root: Path | str | None = None) -> str:
    return git_revision(repo_root) or "unknown"


@lru_cache(maxsize=1)
def current_version() -> str:
    """The running build's revision, resolved once per process.

    Used to stamp every prior and event cheaply — the build cannot change during a
    process's lifetime, so the git lookup runs at most once.
    """
    return version_string()
