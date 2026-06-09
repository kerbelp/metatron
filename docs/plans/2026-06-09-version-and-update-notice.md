# Version Visibility + Passive Update Notice — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `metatron version` command and a passive "update available" notice (CLI startup + web-UI badge) that tells a user when their installed `getmetatron` is behind the latest PyPI release — without ever downloading, executing, or installing anything.

**Architecture:** All logic lives in `metatron/version.py` (it already owns version reporting); the CLI, web server, and UI are thin consumers. A throttled, fail-silent PyPI check (stdlib `urllib`, ~24h cache in `~/.metatron/update_check.json`) plus a user-editable install-provenance file (`~/.metatron/install.json`) feed a single `check_for_update()` returning an `UpdateInfo`. Network is injected in tests and never hit live.

**Tech Stack:** Python 3.12 (pytest, `uv run`); stdlib `urllib.request`/`json`; plain React via CDN for the badge.

**Spec:** `docs/designs/2026-06-09-version-and-update-notice.md`

**Conventions (read before any commit):**
- Public repo — every commit message is a neutral, third-person technical note. Never reference the chat, "the user", or this session.
- Backend tests: `uv run pytest <path> -v`. The full suite: `uv run pytest -q`.
- Branch: `feat/version-update-notice` (stacked on `feat/curation-ux`). No direct commits to `main`.
- **Fail-silent is a hard requirement:** no function in this feature may raise, block startup, or hit the network in a test. The state dir is `~/.metatron` resolved via `METATRON_CONFIG_DIR` (mirror `identity.py:_home`); tests point it at `tmp_path` and inject the fetcher.

---

## File structure

- `metatron/version.py` — MODIFY: add the version-compare, install-detection, provenance, PyPI-check, and notice-format helpers + `UpdateInfo`. (One file owns all of it.)
- `metatron/cli.py` — MODIFY: add the `version` subparser, an early dispatch branch (before catalog setup), and a startup notice in `_cmd_ui`.
- `metatron/webui/api.py` — MODIFY: extend `version()` with the update fields.
- `metatron/webui/app/app.jsx` — MODIFY: render the badge in the nav-rail footer.
- `tests/test_version.py` — CREATE: the real coverage (pure helpers + `check_for_update`).
- `tests/test_cli.py` — MODIFY: `metatron version` output.
- `tests/test_web_api.py` — MODIFY: `/api/version` fields.
- `README.md` — MODIFY: a short note on the update check + opt-out / override env vars.

---

## Task 1: Version comparison + install-method classification (pure helpers)

**Files:**
- Modify: `metatron/version.py`
- Test: `tests/test_version.py` (create)

- [ ] **Step 1: Write failing tests**

Create `tests/test_version.py`:
```python
"""Tests for version reporting + the passive update check (network injected)."""

from metatron import version as V


def test_is_newer_compares_dotted_numerics():
    assert V._is_newer("0.10.0", "0.9.0") is True   # 10 > 9, not string compare
    assert V._is_newer("0.3.0", "0.2.1") is True
    assert V._is_newer("0.2.1", "0.2.1") is False    # equal -> not newer
    assert V._is_newer("0.2.0", "0.3.0") is False
    assert V._is_newer("garbage", "0.2.1") is False  # unparseable -> no notice
    assert V._is_newer("0.2.1", "dev") is False       # dev current -> no notice


def test_classify_install_path():
    assert V._classify_install_path("/opt/homebrew/Cellar/metatron/0.2.1/lib/...")[1] == "brew upgrade metatron"
    assert V._classify_install_path("/Users/x/.local/pipx/venvs/getmetatron/lib/...")[1] == "pipx upgrade getmetatron"
    assert V._classify_install_path("/Users/x/.local/share/uv/tools/getmetatron/lib/...")[1] == "uv tool upgrade getmetatron"
    assert V._classify_install_path("/usr/lib/python3.12/site-packages/metatron/version.py")[1] == "pip install -U getmetatron"
```

- [ ] **Step 2: Run — expect failure**

Run: `uv run pytest tests/test_version.py -v`
Expected: FAIL (`AttributeError: module ... has no attribute '_is_newer'`).

- [ ] **Step 3: Implement the helpers in `metatron/version.py`**

Add these imports at the top (alongside the existing ones):
```python
import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
```

Add the functions (anywhere after the existing ones):
```python
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
```

- [ ] **Step 4: Run — expect pass**

Run: `uv run pytest tests/test_version.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add metatron/version.py tests/test_version.py
git commit -m "feat(version): add version comparison and install-method detection"
```

---

## Task 2: State dir + install provenance (`upgrade_command`)

**Files:**
- Modify: `metatron/version.py`
- Test: `tests/test_version.py`

- [ ] **Step 1: Write failing tests** (append to `tests/test_version.py`)

```python
def test_upgrade_command_env_override_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("METATRON_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("METATRON_INSTALL_CMD", "my-custom upgrade")
    assert V.upgrade_command() == "my-custom upgrade"


def test_upgrade_command_reads_existing_install_json(monkeypatch, tmp_path):
    monkeypatch.delenv("METATRON_INSTALL_CMD", raising=False)
    monkeypatch.setenv("METATRON_CONFIG_DIR", str(tmp_path))
    (tmp_path / "install.json").write_text('{"upgrade_command": "edited-by-user"}')
    assert V.upgrade_command() == "edited-by-user"


def test_upgrade_command_detects_and_persists_once(monkeypatch, tmp_path):
    monkeypatch.delenv("METATRON_INSTALL_CMD", raising=False)
    monkeypatch.setenv("METATRON_CONFIG_DIR", str(tmp_path))
    calls = {"n": 0}
    def fake_detect():
        calls["n"] += 1
        return ("pip", "pip install -U getmetatron")
    monkeypatch.setattr(V, "detect_install_method", fake_detect)
    assert V.upgrade_command() == "pip install -U getmetatron"
    assert (tmp_path / "install.json").exists()       # persisted
    assert V.upgrade_command() == "pip install -U getmetatron"
    assert calls["n"] == 1                              # second call reads the file, no re-detect
```

- [ ] **Step 2: Run — expect failure**

Run: `uv run pytest tests/test_version.py -k upgrade_command -v` → FAIL.

- [ ] **Step 3: Implement in `metatron/version.py`**

```python
def _state_dir() -> Path:
    # Same convention as identity._home(): METATRON_CONFIG_DIR overrides ~/.metatron.
    return Path(os.environ.get("METATRON_CONFIG_DIR", "~/.metatron")).expanduser()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def upgrade_command() -> str:
    """The command to upgrade metatron, by precedence:
    METATRON_INSTALL_CMD env -> ~/.metatron/install.json -> first-run detection (persisted).
    """
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
```

- [ ] **Step 4: Run — expect pass**

Run: `uv run pytest tests/test_version.py -k upgrade_command -v` → PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add metatron/version.py tests/test_version.py
git commit -m "feat(version): record and resolve the upgrade command via install provenance"
```

---

## Task 3: Update-check core (`latest_version`, `check_for_update`, `UpdateInfo`, throttle)

**Files:**
- Modify: `metatron/version.py`
- Test: `tests/test_version.py`

- [ ] **Step 1: Write failing tests** (append)

```python
def _info_env(monkeypatch, tmp_path):
    monkeypatch.setenv("METATRON_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("METATRON_NO_UPDATE_CHECK", raising=False)
    monkeypatch.setenv("METATRON_INSTALL_CMD", "pip install -U getmetatron")
    monkeypatch.setattr(V, "package_version", lambda: "0.2.1")


def test_check_for_update_reports_available(monkeypatch, tmp_path):
    _info_env(monkeypatch, tmp_path)
    info = V.check_for_update(fetch=lambda timeout: {"info": {"version": "0.3.0"}})
    assert info.available is True and info.latest == "0.3.0" and info.current == "0.2.1"
    assert info.command == "pip install -U getmetatron"


def test_check_for_update_not_available_when_current(monkeypatch, tmp_path):
    _info_env(monkeypatch, tmp_path)
    info = V.check_for_update(fetch=lambda timeout: {"info": {"version": "0.2.1"}})
    assert info.available is False


def test_check_for_update_skips_dev_build(monkeypatch, tmp_path):
    _info_env(monkeypatch, tmp_path)
    monkeypatch.setattr(V, "package_version", lambda: "dev")
    assert V.check_for_update(fetch=lambda timeout: {"info": {"version": "9.9.9"}}) is None


def test_check_for_update_disabled_by_env(monkeypatch, tmp_path):
    _info_env(monkeypatch, tmp_path)
    monkeypatch.setenv("METATRON_NO_UPDATE_CHECK", "1")
    assert V.check_for_update(fetch=lambda timeout: {"info": {"version": "9.9.9"}}) is None


def test_check_for_update_throttles(monkeypatch, tmp_path):
    _info_env(monkeypatch, tmp_path)
    calls = {"n": 0}
    def fetch(timeout):
        calls["n"] += 1
        return {"info": {"version": "0.3.0"}}
    V.check_for_update(fetch=fetch)                 # first call hits the fetcher
    V.check_for_update(fetch=fetch)                 # within 24h -> cache, no refetch
    assert calls["n"] == 1
    V.check_for_update(fetch=fetch, force=True)     # force refetches
    assert calls["n"] == 2


def test_check_for_update_fail_silent_on_fetch_error(monkeypatch, tmp_path):
    _info_env(monkeypatch, tmp_path)
    def boom(timeout):
        raise OSError("offline")
    info = V.check_for_update(fetch=boom)
    assert info is not None and info.available is False and info.latest is None


def test_format_update_notice():
    assert V.format_update_notice(None) is None
    assert V.format_update_notice(V.UpdateInfo("0.2.1", "0.2.1", False, "x")) is None
    msg = V.format_update_notice(V.UpdateInfo("0.2.1", "0.3.0", True, "brew upgrade metatron"))
    assert "0.3.0" in msg and "brew upgrade metatron" in msg
```

- [ ] **Step 2: Run — expect failure**

Run: `uv run pytest tests/test_version.py -k "check_for_update or format_update" -v` → FAIL.

- [ ] **Step 3: Implement in `metatron/version.py`**

```python
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


def _read_cache(path: Path):
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


def check_for_update(*, force: bool = False, fetch=None, now: datetime | None = None) -> "UpdateInfo | None":
    """Throttled, fail-silent update check. Returns None when disabled, a dev build,
    or anything goes wrong; otherwise an UpdateInfo (available may be False)."""
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
```

- [ ] **Step 4: Run — expect pass**

Run: `uv run pytest tests/test_version.py -v` → PASS (all). Then `uv run pytest -q` → full suite green.

- [ ] **Step 5: Commit**

```bash
git add metatron/version.py tests/test_version.py
git commit -m "feat(version): add a throttled, fail-silent PyPI update check"
```

---

## Task 4: `metatron version` CLI command

**Files:**
- Modify: `metatron/cli.py` (imports; early dispatch near line 145; subparser near the other `sub.add_parser` calls ~line 610)
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write failing tests** (append to `tests/test_cli.py`)

```python
from metatron import version as V


def test_version_command_prints_version_and_revision(monkeypatch):
    monkeypatch.setattr("metatron.cli.package_version", lambda: "0.3.0")
    monkeypatch.setattr("metatron.cli.version_string", lambda *a, **k: "abc1234")
    monkeypatch.setattr("metatron.cli.check_for_update", lambda: None)
    out = io.StringIO()
    code = main(["version"], out=out)
    assert code == 0
    assert "metatron 0.3.0" in out.getvalue() and "abc1234" in out.getvalue()


def test_version_command_shows_update_notice(monkeypatch):
    monkeypatch.setattr("metatron.cli.package_version", lambda: "0.2.1")
    monkeypatch.setattr("metatron.cli.version_string", lambda *a, **k: "abc1234")
    monkeypatch.setattr("metatron.cli.check_for_update",
                        lambda: V.UpdateInfo("0.2.1", "0.3.0", True, "pip install -U getmetatron"))
    out = io.StringIO()
    main(["version"], out=out)
    assert "update available: 0.3.0" in out.getvalue()
```

- [ ] **Step 2: Run — expect failure**

Run: `uv run pytest tests/test_cli.py -k version_command -v` → FAIL (`version` not a valid choice / no notice).

- [ ] **Step 3: Implement in `metatron/cli.py`**

Add to the imports (find the existing `from metatron.version import ...` if present, else add):
```python
from metatron.version import package_version, version_string, check_for_update, format_update_notice
```

Add the early dispatch right after the bare-command block (`if args.command is None: return _render_home(...)`, ~line 145) — BEFORE `load_settings()` / catalog setup, so `version` works with no configured DB:
```python
    if args.command == "version":
        print(f"metatron {package_version()} (rev {version_string()})", file=out)
        notice = format_update_notice(check_for_update())
        if notice:
            print(notice, file=out)
        return 0
```

Register the subparser next to the others (e.g. after the `ui` parser ~line 610):
```python
    sub.add_parser("version", help="show the installed version and check for updates")
```

- [ ] **Step 4: Run — expect pass**

Run: `uv run pytest tests/test_cli.py -k version_command -v` → PASS (2). Then `uv run pytest tests/test_cli.py -q` → green.

- [ ] **Step 5: Commit**

```bash
git add metatron/cli.py tests/test_cli.py
git commit -m "feat(cli): add a version command that reports build and update availability"
```

---

## Task 5: `metatron ui` startup notice

**Files:**
- Modify: `metatron/cli.py` (`_cmd_ui`, ~line 344; `serve(...)` call ~line 368)

This prints the same notice to stderr as the server starts. The notice logic is already
unit-tested via `format_update_notice` + `check_for_update`; here we just wire it in.
No new test (it would require running the blocking server) — `_cmd_ui` already isn't
unit-tested.

- [ ] **Step 1: Add the notice just before `serve(...)`**

In `_cmd_ui`, immediately before the `serve(` call, add:
```python
    notice = format_update_notice(check_for_update())
    if notice:
        print(notice, file=sys.stderr)
```
(`sys` is already imported in `cli.py` — confirm at the top; it is used elsewhere.)

- [ ] **Step 2: Verify manually**

Run `uv run metatron ui` from the worktree (a source checkout → `package_version()` is `dev` → `check_for_update()` returns None → no notice, no error, server starts normally). This confirms the dev-build skip and that startup isn't blocked. (The populated-notice path is covered by the unit tests.)

- [ ] **Step 3: Commit**

```bash
git add metatron/cli.py
git commit -m "feat(cli): surface the update notice when the curation UI starts"
```

---

## Task 6: `/api/version` fields + web-UI badge

**Files:**
- Modify: `metatron/webui/api.py` (`version()`, ~line 21)
- Modify: `metatron/webui/app/app.jsx` (~line 199, the `.rail-foot` version span)
- Test: `tests/test_web_api.py`

- [ ] **Step 1: Write the failing test** (append to `tests/test_web_api.py`)

```python
from metatron import version as V

def test_version_endpoint_includes_update_fields(monkeypatch):
    from metatron.webui import api as webapi
    monkeypatch.setattr(webapi, "check_for_update",
                        lambda: V.UpdateInfo("0.2.1", "0.3.0", True, "brew upgrade metatron"))
    out = webapi.version()
    assert out["update_available"] is True
    assert out["latest"] == "0.3.0"
    assert out["upgrade_command"] == "brew upgrade metatron"

def test_version_endpoint_handles_no_check(monkeypatch):
    from metatron.webui import api as webapi
    monkeypatch.setattr(webapi, "check_for_update", lambda: None)
    out = webapi.version()
    assert out["update_available"] is False
    assert "version" in out and "revision" in out
```

- [ ] **Step 2: Run — expect failure**

Run: `uv run pytest tests/test_web_api.py -k version_endpoint -v` → FAIL (no such fields / import).

- [ ] **Step 3: Implement in `metatron/webui/api.py`**

Add `check_for_update` to the version import line (find the existing `from metatron.version import package_version, version_string`):
```python
from metatron.version import package_version, version_string, check_for_update
```
Replace `version()`:
```python
def version() -> dict:
    """The version + code revision this server is running (shown in the UI footer),
    plus whether a newer release is available on PyPI (passive notice only)."""
    out = {"version": package_version(), "revision": version_string()}
    info = check_for_update()
    if info:
        out.update({"latest": info.latest, "update_available": info.available,
                    "upgrade_command": info.command})
    else:
        out["update_available"] = False
    return out
```

- [ ] **Step 4: Run — expect pass**

Run: `uv run pytest tests/test_web_api.py -k version_endpoint -v` → PASS (2). Then `uv run pytest -q` → full suite green.

- [ ] **Step 5: Add the badge in `app.jsx`** (STRAIGHT ASCII QUOTES ONLY — this is the no-build-step app; a smart quote breaks Babel)

In the `.rail-foot` block (~line 199), right after the existing version `<span>...</span>`, add:
```jsx
{ver.data && ver.data.update_available && (
  <span className="chip" title={"v" + ver.data.latest + " · run: " + ver.data.upgrade_command}
    style={{ marginLeft: 8, fontSize: 9, color: "var(--amber)", borderColor: "rgba(245,193,107,.3)" }}>
    update available
  </span>
)}
```
(Confirm the `chip` class exists — it is used throughout `views_knowledge.jsx`.)

- [ ] **Step 6: Verify the badge manually**

The dev server reports `dev` (no badge locally). To smoke-test rendering without a real update, temporarily confirm the markup compiles by loading the UI (no Babel parse error in the console) — the populated path is covered by the API test. Do NOT commit any temporary stub.

- [ ] **Step 7: Commit**

```bash
git add metatron/webui/api.py metatron/webui/app/app.jsx tests/test_web_api.py
git commit -m "feat(webui): expose update availability and show an update badge in the footer"
```

---

## Task 7: README note (privacy + opt-out)

**Files:**
- Modify: `README.md` (near the installation / notes section)

- [ ] **Step 1: Add a short note**

Add a brief paragraph documenting the behavior, e.g.:
```markdown
### Update notices

`metatron version` and the curation UI check PyPI at most once a day for a newer
`getmetatron` release and print a passive notice with the upgrade command. The check
is a read-only request to pypi.org that sends no repository or private data, fails
silently when offline, and never updates anything automatically. Disable it with
`METATRON_NO_UPDATE_CHECK=1`. Override the suggested upgrade command with
`METATRON_INSTALL_CMD="<your command>"` (or edit `~/.metatron/install.json`).
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: document the passive update notice and its opt-out"
```

---

## Final verification

- [ ] `uv run pytest -q` — full suite green (new `tests/test_version.py` + the additions).
- [ ] `uv run metatron version` — prints `metatron <ver> (rev <hash>)`; from a source checkout it shows no update line (dev build); set `METATRON_NO_UPDATE_CHECK=1` and confirm it still prints cleanly.
- [ ] `uv run metatron ui` — starts normally with no notice from a dev checkout (proves fail-silent + dev-skip + non-blocking).
- [ ] Confirm commit/PR text is neutral and third-person.
- [ ] Merge order when finishing: `feat/curation-ux` → `feat/version-update-notice` → bump the minor version in `pyproject.toml`.

## Notes for the implementer

- **Never hit the network in a test.** Every `check_for_update`/`latest_version` test injects `fetch=`. Every state-file test sets `METATRON_CONFIG_DIR` to a `tmp_path`.
- **Fail-silent is load-bearing.** The broad `except Exception` in `check_for_update`/`latest_version` is intentional (a stale-version nicety must never break a real command or block the server). Keep the `# noqa: BLE001` notes.
- **`version` must not require a DB.** Its dispatch is placed before catalog setup in `main()` on purpose; do not move it below `load_settings()`.
- The frontend badge is the only non-Python change and has no automated test — keep it presentational and quote-clean.
