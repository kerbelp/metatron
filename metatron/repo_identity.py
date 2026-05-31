"""Derive a stable identifier for a repo from its git remote.

A repo's identity must be **constant across developers and machines**, so we key
on the ``origin`` remote (normalized) rather than the local checkout path, which
varies per dev. An explicit override is honored; if there's no remote at all we
fall back to the directory name (and the caller can override).
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


def normalize_remote(url: str) -> str:
    """Normalize a git remote URL to ``host/path`` (no scheme, user, or .git)."""
    url = url.strip()
    # scp-like syntax: git@host:org/repo(.git)
    scp = re.match(r"^[\w.-]+@([\w.-]+):(.+)$", url)
    if scp:
        host, path = scp.group(1), scp.group(2)
    else:
        # strip scheme://[user@]
        without_scheme = re.sub(r"^[a-zA-Z][\w+.-]*://", "", url)
        without_scheme = re.sub(r"^[\w.-]+@", "", without_scheme)
        host, _, path = without_scheme.partition("/")
    path = path.strip("/")
    if path.endswith(".git"):
        path = path[: -len(".git")]
    return f"{host}/{path}"


def repo_id(repo_path: str | Path, override: str | None = None) -> str:
    """A stable id for the repo at ``repo_path``.

    Order: explicit ``override`` > normalized ``origin`` remote > directory name.
    """
    if override:
        return override
    result = subprocess.run(
        ["git", "-C", str(repo_path), "remote", "get-url", "origin"],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0 and result.stdout.strip():
        return normalize_remote(result.stdout.strip())
    return Path(repo_path).resolve().name
