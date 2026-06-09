# Design: version visibility + passive update notice

- **Date:** 2026-06-09
- **Status:** approved
- **Surface:** the `metatron` CLI and the local curation web UI.
- **Branch:** `feat/version-update-notice`, stacked on `feat/curation-ux` (it extends
  the same `/api/version` endpoint and UI header). Merge order: `feat/curation-ux`
  → this → minor version bump.

## Goal

Make it obvious when an installed `metatron` is behind the latest release, so a user
isn't unknowingly running a stale build. Two pieces:

1. A `metatron version` command that prints the installed version and git revision.
2. A passive **update notice** — on `metatron ui` startup (CLI) and as a small badge
   in the web UI header — when a newer `getmetatron` release exists on PyPI, with the
   command to upgrade.

This is **notice only**: it never downloads, executes, or installs anything. That
respects the project's on-prem posture and the deferred-packaging scope rule
(`CLAUDE.md`: "Deployment infra and packaging for distribution — build none of them
yet"). Auto-update was explicitly declined.

## The line we hold

- **No automatic code execution.** The only outbound action is a throttled,
  disable-able, read-only HTTP GET to `pypi.org` for the package's public JSON. No
  repo content or private data leaves the machine.
- **Fail-silent everywhere.** Offline, air-gapped, disabled, dev build, parse error,
  timeout → simply no notice. The check must never block startup, slow a command
  perceptibly, or raise.
- **Out of scope:** auto-update/restart; modifying the hosted `install.sh` (a
  separate site-repo follow-up); touching `metatron_setup.sh` (it onboards repos, it
  does not install metatron).

## Components

All new logic lands in `metatron/version.py` (it already owns version reporting),
keeping the CLI, server, and UI as thin consumers.

### `metatron/version.py` (new functions)

State lives under the existing config dir — `Path(os.environ.get(
"METATRON_CONFIG_DIR", "~/.metatron")).expanduser()` (the same dir `identity.py`
uses). Two small JSON files there:

- `update_check.json` — throttle cache: `{ "checked_at": <iso>, "latest": <str|null> }`.
- `install.json` — install provenance: `{ "method": <str>, "upgrade_command": <str>,
  "source": <"detected"|"env">, "recorded_at": <iso> }`. Written once (first run /
  env), then read; **user-editable**.

Functions:

- `latest_version(timeout=1.5) -> str | None` — GET
  `https://pypi.org/pypi/getmetatron/json` via stdlib `urllib.request`, return
  `data["info"]["version"]`. No new dependency. Any error / timeout / non-200 →
  `None`.
- `_is_newer(latest, current) -> bool` — self-contained comparison: split each
  version on `.`, coerce the leading numeric components to ints, compare as tuples
  (e.g. `0.10.0 > 0.9.0`). No `packaging` dependency (it is not declared in
  `pyproject.toml`, and PyPI release versions here are standard dotted numerics).
  Anything that doesn't parse cleanly → `False` (no notice). Equal → `False`.
- `detect_install_method() -> tuple[str, str]` — best-effort `(method, command)` from
  the install path (`Path(__file__)` / `sys.prefix` / `sys.argv[0]`):
  - `/Cellar/` or `/opt/homebrew/` → `("homebrew", "brew upgrade metatron")`
  - `/pipx/` → `("pipx", "pipx upgrade getmetatron")`
  - `/uv/tools/` → `("uv", "uv tool upgrade getmetatron")`
  - else → `("pip", "pip install -U getmetatron")`
- `upgrade_command() -> str` — resolves the command by precedence:
  1. `METATRON_INSTALL_CMD` env var (explicit override), else
  2. `install.json` if present, else
  3. `detect_install_method()` — and **persist** the result to `install.json`
     (`source: "detected"`) so detection runs once and stays correctable.
- `check_for_update(*, force=False) -> UpdateInfo | None` — orchestrator:
  - Return `None` if `METATRON_NO_UPDATE_CHECK` is set, or `package_version() == "dev"`
    (running from source).
  - Read `update_check.json`; if `checked_at` is within ~24h and not `force`, reuse the
    cached `latest`; otherwise call `latest_version()` and rewrite the cache.
  - Return `UpdateInfo(current=package_version(), latest, available=_is_newer(latest,
    current), command=upgrade_command())`. `latest is None` or not newer →
    `available=False`.
  - Wrapped so any unexpected error → `None`.
- `UpdateInfo` — a small frozen dataclass: `current, latest, available, command`.

### `metatron version` CLI command (`cli.py`)

`sub.add_parser("version", ...)`. Handler prints `metatron <package_version()> (rev
<version_string()>)` — note `package_version()` is the installed semver (e.g. `0.3.0`,
or `dev`) and `version_string()` is the git short hash (or `unknown`). Then `info =
check_for_update()`; if `info and info.available`, print a second line: `→ update
available: <latest>  (run: <command>)`. Fail-silent.

### `metatron ui` startup notice (`cli.py` `_cmd_ui`)

Just before `serve(...)` is invoked, call `check_for_update()` **synchronously** and,
if available, print the same one-line notice to **stderr**. No threading: the common
path is a cache read (no network), and the worst case is a single timeout-bounded
(~1.5s) fetch at most once per ~24h — acceptable for a CLI startup. Fail-silent, so it
never prevents the server from starting.

### Web UI badge

- `webui/api.py` `version()` — extend the response to `{ version, revision, latest,
  update_available, upgrade_command }`, sourced from `check_for_update()` (the cache
  means the UI's poll never hits PyPI live beyond the daily throttle; on a cache miss
  it does one bounded fetch). On `None`, return `update_available: false` and omit /
  null the extra fields.
- `webui/app/app.jsx` — the version indicator is in the **nav-rail footer** (~line
  199, the `v{ver.data.version}` span, not a top header bar). When
  `ver.data.update_available`, render a small amber "update available" chip adjacent
  to it; `title` = `v{latest} · run: {upgrade_command}`. Presentational only.

## Error handling

Every path is fail-silent: a missing/locked/corrupt state file, no network, a
non-200, a timeout, an unparseable version — all degrade to "no notice." Nothing in
this feature can crash a command or block the server. Writes to the state files are
best-effort (a write failure is ignored).

## Testing

- **`version.py` (pytest)** — the real coverage; the network fetch is **injected**
  (function arg / monkeypatch), never hit live, and the config dir is pointed at a
  `tmp_path`:
  - `_is_newer`: newer / equal / older / unparseable.
  - `detect_install_method`: homebrew / pipx / uv / pip sample paths.
  - `upgrade_command`: env override wins; existing `install.json` is read; first-run
    detection writes `install.json` and is reused (no re-detect); a user-edited file
    is respected.
  - `check_for_update`: available / not-available / `latest is None`; `dev` build
    skip; `METATRON_NO_UPDATE_CHECK` skip; 24h throttle (a fetch-counter proves no
    refetch within the window; `force` refetches); fail-silent when the fetcher
    raises.
- **`metatron version` (pytest, via the `test_cli.py` pattern)** — output contains
  version + revision; with an injected available `UpdateInfo`, contains the notice
  line.
- **`/api/version` (pytest, `test_web_api.py`)** — returns the new fields from an
  injected/cached `UpdateInfo`; no live network in the test.
- **Frontend badge** — presentational from the API fields; no extractable logic worth
  a `node:test`. Verified manually against the running UI.

## Risks & mitigations

- **Phoning PyPI from an on-prem tool.** Mitigated by: opt-out env var, ~24h throttle
  (not per-startup), short timeout, fail-silent, and a public read-only GET that sends
  no private data. Documented in the README's privacy/notes section as part of this
  change.
- **Wrong upgrade command for an unusual install.** `install.json` is user-editable
  and `METATRON_INSTALL_CMD` overrides; detection is only the fallback. We do not, and
  cannot, capture the literal install command for wheel installs — this is acknowledged,
  not worked around.
- **Startup latency.** The check is throttled and timeout-bounded; the common path is a
  cache read (no network). Worst case is one ~1.5s bounded fetch once per day.
