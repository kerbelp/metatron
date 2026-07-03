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
    """Leading-numeric dotted parse: '0.10.0' -> (0, 10, 0). None if not parseable.

    # Plain X.Y.Z only; PEP 440 pre/post suffixes (e.g. "1.2.3.post1") parse to None,
    # which conservatively yields no update notice. This project ships plain releases.
    """
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
    if "/pipx/" in p:
        return ("pipx", "pipx upgrade getmetatron")
    if "/uv/tools/" in p:
        return ("uv", "uv tool upgrade getmetatron")
    return ("pip", "pip install -U getmetatron")


def detect_install_method() -> tuple[str, str]:
    """(method, upgrade_command) for how this package appears to be installed."""
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


# ---------------------------------------------------------------------------
# Update-check core (latest_version, check_for_update, UpdateInfo, throttle,
# format_update_notice)
# ---------------------------------------------------------------------------

_THROTTLE = timedelta(hours=24)


@dataclass(frozen=True)
class UpdateInfo:
    current: str
    latest: str | None
    available: bool
    command: str


def _fetch_pypi(timeout: float) -> dict:
    import urllib.request
    with urllib.request.urlopen(
        "https://pypi.org/pypi/getmetatron/json", timeout=timeout
    ) as resp:
        return json.loads(resp.read().decode())


def latest_version(timeout: float = 1.5, *, fetch=None) -> str | None:
    """Latest released version on PyPI, or None on any error/timeout. Never raises."""
    fetch = fetch or _fetch_pypi
    try:
        return fetch(timeout)["info"]["version"]
    except Exception:  # noqa: BLE001 - network/parse/whatever -> no notice
        return None


def _read_cache(path: Path) -> tuple[datetime, str | None] | None:
    try:
        data = json.loads(path.read_text())
        return datetime.fromisoformat(data["checked_at"]), data.get("latest")
    except (OSError, ValueError, KeyError):
        return None


def _write_cache(path: Path, when: datetime, latest: str | None) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"checked_at": when.isoformat(), "latest": latest}))
    except OSError:
        pass


def check_for_update(*, force: bool = False, fetch=None, now: datetime | None = None, cache_only: bool = False) -> "UpdateInfo | None":
    """Throttled, fail-silent update check. Returns None when disabled, a dev build,
    or anything goes wrong; otherwise an UpdateInfo (available may be False).

    ``cache_only=True`` is for the request-serving path (e.g. the web API endpoint):
    it reads the on-disk cache but never hits the network, so a single-threaded server
    cannot block on a PyPI fetch. When the cache is absent it returns an UpdateInfo
    with available=False and latest=None. CLI paths and startup should call without
    this flag so they warm the cache that the server then reads."""
    try:
        if os.environ.get("METATRON_NO_UPDATE_CHECK"):
            return None
        current = package_version()
        if current == "dev":
            return None
        now = now or datetime.now(timezone.utc)
        cache = _state_dir() / "update_check.json"
        cached = _read_cache(cache)
        if cached and not force and (now - cached[0]) < _THROTTLE:
            latest = cached[1]
        elif cache_only:
            latest = cached[1] if cached else None   # server path: never blocks on PyPI
        else:
            latest = latest_version(fetch=fetch)
            _write_cache(cache, now, latest)
        available = bool(latest) and _is_newer(latest, current)
        return UpdateInfo(current=current, latest=latest, available=available, command=upgrade_command())
    except Exception:  # noqa: BLE001 - never let the check break a caller
        return None


def format_update_notice(info: "UpdateInfo | None") -> str | None:
    if not (info and info.available):
        return None
    return f"→ update available: {info.latest}  (run: {info.command})"
