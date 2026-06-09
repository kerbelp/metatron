"""Report the code revision being served.

The curation UI shows this so you can tell which commit a running server is on —
servers load the code once at startup and do not hot-reload, so "which version is
this?" is a real question. Resolved from git at the package location, with a plain
fallback when git/the repo is unavailable (e.g. an installed wheel).
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from pathlib import Path


def package_version() -> str:
    """The installed package version (e.g. ``0.2.1``), or ``dev`` if not installed."""
    try:
        return _pkg_version("getmetatron")
    except PackageNotFoundError:
        return "dev"


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

    Used to stamp every decision and event cheaply — the build cannot change during a
    process's lifetime, so the git lookup runs at most once.
    """
    return version_string()


# ---------------------------------------------------------------------------
# Version comparison + install-method classification
# ---------------------------------------------------------------------------

def _parse_version(v: str) -> tuple[int, ...] | None:
    """Leading-numeric dotted parse: '0.10.0' -> (0, 10, 0). None if not parseable."""
    parts: list[int] = []
    for chunk in str(v).split("."):
        digits = ""
        for ch in chunk:
            if ch.isdigit():
                digits += ch
            else:
                break
        if not digits:
            return None
        parts.append(int(digits))
    return tuple(parts) if parts else None


def _is_newer(latest: str, current: str) -> bool:
    lp, cp = _parse_version(latest), _parse_version(current)
    if lp is None or cp is None:
        return False
    return lp > cp


def _classify_install_path(path: str) -> tuple[str, str]:
    """(method, upgrade_command) inferred from where the package is installed."""
    p = path.lower()
    if "/cellar/" in p or "/opt/homebrew/" in p:
        return ("homebrew", "brew upgrade metatron")
    if "/pipx/" in p:
        return ("pipx", "pipx upgrade getmetatron")
    if "/uv/tools/" in p:
        return ("uv", "uv tool upgrade getmetatron")
    return ("pip", "pip install -U getmetatron")


def detect_install_method() -> tuple[str, str]:
    return _classify_install_path(str(Path(__file__).resolve()))


# ---------------------------------------------------------------------------
# State dir + install provenance (upgrade_command)
# ---------------------------------------------------------------------------

def _state_dir() -> Path:
    # Same convention as identity._home(): METATRON_CONFIG_DIR overrides ~/.metatron.
    return Path(os.environ.get("METATRON_CONFIG_DIR", "~/.metatron")).expanduser()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def upgrade_command() -> str:
    """Command to upgrade metatron, by precedence:
    METATRON_INSTALL_CMD env -> ~/.metatron/install.json -> first-run detection (persisted)."""
    env = os.environ.get("METATRON_INSTALL_CMD")
    if env:
        return env
    path = _state_dir() / "install.json"
    try:
        data = json.loads(path.read_text())
        cmd = data.get("upgrade_command")
        if cmd:
            return cmd
    except (OSError, ValueError):
        pass
    method, cmd = detect_install_method()
    try:  # best-effort persist so detection runs once and stays user-editable
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(
            {"method": method, "upgrade_command": cmd, "source": "detected",
             "recorded_at": _now_iso()}, indent=2))
    except OSError:
        pass
    return cmd
