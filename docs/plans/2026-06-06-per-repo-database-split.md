# Per-repo database split — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the single shared `metatron.db` into one self-contained SQLite file per repo, so a repo's decisions become a shippable hand-off artifact, while the CLI, MCP server, and local UI keep working seamlessly across repos.

**Architecture:** A new `Catalog` (in `metatron/storage/catalog.py`) owns a data directory (default `~/.metatron/`) of `<slug>.db` files, each self-describing via a one-row `repo_meta` table. Catalog-backed store classes implement the existing `DecisionStore`/`EventStore`/`IngestRunStore` interfaces by routing each call to the right per-repo file (fanning out when a query spans all repos), so callers stay unchanged — only store *construction* in `cli.main()` moves to the catalog. A one-time auto-migration splits a legacy `metatron.db` into per-repo files and archives the original. `metatron export <repo>` copies a repo's file out for hand-off; pointing `--db` at a single file enters single-file mode for the recipient.

**Tech Stack:** Python 3.12+, stdlib `sqlite3`, `pytest`, `uv`. (Run tests with `uv run -m pytest`; run scripts with `uv run python` — bare `python`/`pytest` are not on PATH here.)

**Spec:** `docs/designs/2026-06-06-per-repo-database-split.md`

---

## Refinement vs. the spec (read first)

The spec said callers would use an `open_repo(...)` helper and that there would be "no cross-file id search." Implementation reveals the **local UI is genuinely cross-repo** (it serves all repos from one `store`, filters by a `repo` query param, and mutates decisions by id with no repo in scope). To keep the UI, CLI, and serve code untouched, this plan implements **catalog-backed stores that satisfy the existing interface and route by `repo`**, with bounded fan-out for the few cross-repo operations (`repo=None` listings; id-only `get`/`set_status`/`set_triage`/`mark_handled`). The hot `get_decisions_for_context` path stays single-file because it is always repo-scoped. `catalog.open(repo)` (single-repo access) still exists and is used by `export` and single-file recipient mode. This is a faithful, smaller-diff realization of the spec's intent; flag it in review.

## File structure

- **Create** `metatron/storage/catalog.py` — `Catalog` (dir/file modes, `list_repos`, `open`, `path_for`, slug), `_ensure_repo_meta`/`_read_repo_id`, and the catalog-backed `CatalogDecisionStore` / `CatalogEventStore` / `CatalogIngestRunStore`.
- **Create** `metatron/storage/migrate.py` — `migrate_legacy_db(legacy_path, catalog)`; idempotent split + archive.
- **Modify** `metatron/storage/sqlite.py` — add the `repo_meta` table (`CREATE TABLE IF NOT EXISTS`) so any per-repo file always has it; expose the file path on each store (`self.path`) for `export`.
- **Modify** `metatron/config.py` — default `db_path` → `~/.metatron`; add `DEFAULT_DATA_DIR`.
- **Modify** `metatron/cli.py` — build the `Catalog` + catalog-backed stores in `main()`; trigger migration once; add the `export` subcommand and `_cmd_export`. `_resolve_repo` is unchanged (it calls `store.list_repos()`, which the catalog store implements).
- **Create** test files: `tests/test_catalog.py`, `tests/test_catalog_stores.py`, `tests/test_migrate.py`, `tests/test_cli_export.py`; extend `tests/test_cli.py` (single-file mode / catalog resolution) and add an end-to-end test.

---

## Task 1 (PR #1): Catalog foundation + `repo_meta`

**Files:**
- Modify: `metatron/storage/sqlite.py`
- Create: `metatron/storage/catalog.py`
- Test: `tests/test_catalog.py`

### 1a. `repo_meta` table on per-repo files

- [ ] **Step 1 — failing test** (`tests/test_catalog.py`):

```python
import sqlite3
from pathlib import Path

from metatron.storage.catalog import Catalog, slug_for


def test_slug_is_deterministic_readable_and_collision_safe():
    a = slug_for("github.com/acme/app")
    b = slug_for("gitlab.com/acme/app")
    assert a.endswith(".db") and a.startswith("app-")
    assert slug_for("github.com/acme/app") == a   # deterministic
    assert a != b                                  # same tail, different id → different file


def test_open_creates_self_describing_file(tmp_path):
    cat = Catalog(str(tmp_path))
    stores = cat.open("github.com/acme/app")
    path = cat.path_for("github.com/acme/app")
    assert path.exists()
    row = sqlite3.connect(path).execute("SELECT repo_id FROM repo_meta").fetchone()
    assert row[0] == "github.com/acme/app"
    stores.decisions.close(); stores.events.close(); stores.runs.close()
```

- [ ] **Step 2 — run, expect fail:** `uv run -m pytest tests/test_catalog.py -q` → ImportError (`catalog` missing).

- [ ] **Step 3 — implement** `metatron/storage/catalog.py`:

```python
"""The repo catalog: one self-contained SQLite file per repo.

A repo's data (decisions, events, ingest runs) lives in its own ``<slug>.db`` inside a
data directory (default ``~/.metatron``). Each file carries a one-row ``repo_meta``
table so it is self-describing — a handed-off file announces its repo id regardless
of filename. The :class:`Catalog` is the only thing that knows files exist; callers
use the catalog-backed stores, which route every call to the right file.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from metatron.storage.sqlite import (
    SQLiteEventStore,
    SQLiteIngestRunStore,
    SQLiteDecisionStore,
)

_META_SCHEMA = "CREATE TABLE IF NOT EXISTS repo_meta (repo_id TEXT NOT NULL)"


def slug_for(repo_id: str) -> str:
    """A readable, collision-safe filename for a repo id.

    Keeps the last path segment for humans (``github.com/acme/app`` → ``app-…``) and
    appends a short hash of the *full* id so distinct repos with the same tail never
    share a file. The truth is ``repo_meta``; this is only a stable handle.
    """
    tail = repo_id.rstrip("/").split("/")[-1] or "repo"
    tail = re.sub(r"[^A-Za-z0-9._-]+", "-", tail).strip("-").lower() or "repo"
    digest = hashlib.sha1(repo_id.encode("utf-8")).hexdigest()[:6]
    return f"{tail}-{digest}.db"


def _read_repo_id(path: Path) -> str | None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(_META_SCHEMA)
        row = conn.execute("SELECT repo_id FROM repo_meta LIMIT 1").fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def _ensure_repo_meta(path: Path, repo_id: str) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(_META_SCHEMA)
        if conn.execute("SELECT 1 FROM repo_meta LIMIT 1").fetchone() is None:
            conn.execute("INSERT INTO repo_meta (repo_id) VALUES (?)", (repo_id,))
            conn.commit()
    finally:
        conn.close()


@dataclass
class RepoStores:
    decisions: SQLiteDecisionStore
    events: SQLiteEventStore
    runs: SQLiteIngestRunStore


class Catalog:
    """Owns the data directory (or, in single-file mode, one file)."""

    def __init__(self, path: str | Path) -> None:
        p = Path(path).expanduser()
        # Single-file mode: an existing regular file is treated as the whole world
        # (the recipient's handed-off DB). Otherwise ``path`` is a catalog directory.
        self._single_file = p.is_file()
        if self._single_file:
            self._file = p
        else:
            self._dir = p
            self._dir.mkdir(parents=True, exist_ok=True)
        self._open: dict[str, RepoStores] = {}

    def path_for(self, repo_id: str) -> Path:
        return self._file if self._single_file else self._dir / slug_for(repo_id)

    def list_repos(self) -> list[str]:
        if self._single_file:
            rid = _read_repo_id(self._file)
            return [rid] if rid else []
        ids: list[str] = []
        for f in sorted(self._dir.glob("*.db")):
            rid = _read_repo_id(f)
            if rid and rid not in ids:   # de-dupe a manually copied file
                ids.append(rid)
        return sorted(ids)

    def open(self, repo_id: str) -> RepoStores:
        if repo_id in self._open:
            return self._open[repo_id]
        path = self.path_for(repo_id)
        _ensure_repo_meta(path, repo_id)
        stores = RepoStores(
            SQLiteDecisionStore(str(path)),
            SQLiteEventStore(str(path)),
            SQLiteIngestRunStore(str(path)),
        )
        self._open[repo_id] = stores
        return stores

    def close(self) -> None:
        for s in self._open.values():
            s.decisions.close(); s.events.close(); s.runs.close()
        self._open.clear()
```

- [ ] **Step 4 — run, expect pass:** `uv run -m pytest tests/test_catalog.py -q`.

- [ ] **Step 5 — add `self.path` to the three stores** (`metatron/storage/sqlite.py`), so `export` can locate the file. In each `__init__` add `self.path = path` right after the `sqlite3.connect(...)` line (three stores). Also add the `repo_meta` table defensively so a file opened directly always has it — append to each store's schema setup:

```python
self._conn.execute("CREATE TABLE IF NOT EXISTS repo_meta (repo_id TEXT NOT NULL)")
```

- [ ] **Step 6 — run full suite:** `uv run -m pytest -q` (expect existing 334 + new passing).

- [ ] **Step 7 — single-file mode test** (`tests/test_catalog.py`): create a file via `Catalog(dir).open("r")`, then `Catalog(str(path_for_r))` and assert `list_repos() == ["r"]` and `path_for("anything") == that file`.

- [ ] **Step 8 — commit:**

```bash
git add metatron/storage/catalog.py metatron/storage/sqlite.py tests/test_catalog.py
git commit -m "storage: add per-repo Catalog and repo_meta self-describing files"
```

---

## Task 2 (PR #2): Catalog-backed stores (routing + fan-out)

**Files:**
- Modify: `metatron/storage/catalog.py`
- Test: `tests/test_catalog_stores.py`

These implement `DecisionStore` / `EventStore` / `IngestRunStore` over the catalog: route by `repo`, fan out when `repo is None`, search files for id-only ops.

- [ ] **Step 1 — failing tests** (`tests/test_catalog_stores.py`):

```python
from metatron.models import Origin, Decision, Status
from metatron.events import Event, EventKind
from metatron.storage.catalog import Catalog, CatalogDecisionStore, CatalogEventStore


def _decision(repo, pattern):
    return Decision(repo=repo, pattern=pattern, scope="app", rationale="r",
                 origin=Origin.BOOTSTRAP, status=Status.CANONICAL)


def test_add_routes_to_repo_file_and_list_repos_aggregates(tmp_path):
    store = CatalogDecisionStore(Catalog(str(tmp_path)))
    store.add(_decision("repoA", "alpha"))
    store.add(_decision("repoB", "beta"))
    assert store.list_repos() == ["repoA", "repoB"]
    assert [p.pattern for p in store.list(repo="repoA")] == ["alpha"]
    assert {p.pattern for p in store.list()} == {"alpha", "beta"}   # repo=None fans out


def test_get_and_set_status_find_owning_file(tmp_path):
    store = CatalogDecisionStore(Catalog(str(tmp_path)))
    p = store.add(_decision("repoA", "alpha"))
    assert store.get(p.id).pattern == "alpha"          # id-only search
    store.set_status(p.id, Status.REJECTED)
    assert store.get(p.id).status is Status.REJECTED


def test_event_store_routes_and_resolves_by_id(tmp_path):
    es = CatalogEventStore(Catalog(str(tmp_path)))
    e = es.record(Event(repo="repoA", kind=EventKind.QUERY, decision_ids=["x"]))
    assert es.get(e.id).repo == "repoA"
    assert es.count_events() == 1
```

- [ ] **Step 2 — run, expect fail:** `uv run -m pytest tests/test_catalog_stores.py -q` (ImportError).

- [ ] **Step 3 — implement** the three stores in `catalog.py` (append). Pattern: repo-scoped → one file; `repo=None` → merge across `list_repos()`, re-sort newest-first, then apply `limit`/`offset` to the merged result; id-only → iterate files. Full code:

```python
from metatron.events import Event
from metatron.models import IngestRun, Origin, Decision, Status, TriageVerdict
from metatron.storage.base import EventStore, DecisionStore


class CatalogDecisionStore(DecisionStore):
    def __init__(self, catalog: Catalog) -> None:
        self._cat = catalog

    def _p(self, repo_id: str) -> SQLiteDecisionStore:
        return self._cat.open(repo_id).decisions

    def add(self, decision: Decision) -> Decision:
        return self._p(decision.repo).add(decision)

    def list(self, *, repo=None, status=None, scope=None, model=None,
             triage=None, origin=None, search=None, limit=None, offset=0):
        kw = dict(status=status, scope=scope, model=model, triage=triage,
                  origin=origin, search=search)
        if repo is not None:
            return self._p(repo).list(repo=repo, limit=limit, offset=offset, **kw)
        merged: list[Decision] = []
        for rid in self._cat.list_repos():
            merged.extend(self._p(rid).list(repo=rid, **kw))
        merged.sort(key=lambda p: (p.created_at, p.id), reverse=True)
        if limit is not None:
            return merged[offset:offset + limit]
        return merged[offset:]

    def count(self, *, repo=None, **kw):
        if repo is not None:
            return self._p(repo).count(repo=repo, **kw)
        return sum(self._p(rid).count(repo=rid, **kw) for rid in self._cat.list_repos())

    def get(self, decision_id: str):
        for rid in self._cat.list_repos():
            hit = self._p(rid).get(decision_id)
            if hit is not None:
                return hit
        return None

    def _owner(self, decision_id: str) -> str:
        for rid in self._cat.list_repos():
            if self._p(rid).get(decision_id) is not None:
                return rid
        raise KeyError(decision_id)

    def set_status(self, decision_id: str, status: Status) -> Decision:
        return self._p(self._owner(decision_id)).set_status(decision_id, status)

    def set_triage(self, decision_id: str, verdict: TriageVerdict, reason: str) -> Decision:
        return self._p(self._owner(decision_id)).set_triage(decision_id, verdict, reason)

    def list_repos(self) -> list[str]:
        return self._cat.list_repos()


class CatalogEventStore(EventStore):
    def __init__(self, catalog: Catalog) -> None:
        self._cat = catalog

    def _e(self, repo_id: str) -> SQLiteEventStore:
        return self._cat.open(repo_id).events

    def record(self, event: Event) -> Event:
        return self._e(event.repo).record(event)

    def get(self, event_id: str):
        for rid in self._cat.list_repos():
            hit = self._e(rid).get(event_id)
            if hit is not None:
                return hit
        return None

    def unhandled_feedback(self, *, repo=None):
        rids = [repo] if repo is not None else self._cat.list_repos()
        out: list[Event] = []
        for rid in rids:
            out.extend(self._e(rid).unhandled_feedback(repo=rid))
        out.sort(key=lambda e: e.timestamp)
        return out

    def mark_handled(self, event_id: str, produced_ids: list[str]) -> None:
        for rid in self._cat.list_repos():
            if self._e(rid).get(event_id) is not None:
                self._e(rid).mark_handled(event_id, produced_ids)
                return

    def list_events(self, *, repo=None, limit=None, offset=0):
        if repo is not None:
            return self._e(repo).list_events(repo=repo, limit=limit, offset=offset)
        merged: list[Event] = []
        for rid in self._cat.list_repos():
            merged.extend(self._e(rid).list_events(repo=rid))
        merged.sort(key=lambda e: (e.timestamp, e.id), reverse=True)
        return merged[offset:offset + limit] if limit is not None else merged[offset:]

    def count_events(self, *, repo=None):
        if repo is not None:
            return self._e(repo).count_events(repo=repo)
        return sum(self._e(r).count_events(repo=r) for r in self._cat.list_repos())


class CatalogIngestRunStore:
    def __init__(self, catalog: Catalog) -> None:
        self._cat = catalog

    def record(self, run: IngestRun) -> IngestRun:
        return self._cat.open(run.repo).runs.record(run)

    def list_for_repo(self, repo):
        if repo is not None:
            return self._cat.open(repo).runs.list_for_repo(repo)
        out: list[IngestRun] = []
        for rid in self._cat.list_repos():
            out.extend(self._cat.open(rid).runs.list_for_repo(rid))
        out.sort(key=lambda r: (r.timestamp, r.id), reverse=True)
        return out
```

- [ ] **Step 4 — run, expect pass:** `uv run -m pytest tests/test_catalog_stores.py -q`.

- [ ] **Step 5 — run full suite:** `uv run -m pytest -q`.

- [ ] **Step 6 — commit:**

```bash
git add metatron/storage/catalog.py tests/test_catalog_stores.py
git commit -m "storage: catalog-backed DecisionStore/EventStore/IngestRunStore routing"
```

---

## Task 3 (PR #3): Auto-split migration of legacy `metatron.db`

**Files:**
- Create: `metatron/storage/migrate.py`
- Test: `tests/test_migrate.py`

- [ ] **Step 1 — failing test** (`tests/test_migrate.py`):

```python
from datetime import datetime, timezone
from pathlib import Path

from metatron.models import Origin, Decision, Status
from metatron.events import Event, EventKind
from metatron.storage.sqlite import SQLiteDecisionStore, SQLiteEventStore
from metatron.storage.catalog import Catalog, CatalogDecisionStore
from metatron.storage.migrate import migrate_legacy_db


def _seed_legacy(path):
    ps = SQLiteDecisionStore(str(path)); es = SQLiteEventStore(str(path))
    for repo in ("repoA", "repoB"):
        ps.add(Decision(repo=repo, pattern=f"p-{repo}", scope="app", rationale="r",
                     origin=Origin.BOOTSTRAP, status=Status.CANONICAL))
        es.record(Event(repo=repo, kind=EventKind.QUERY, decision_ids=["x"]))
    ps.close(); es.close()


def test_migrate_splits_per_repo_and_archives(tmp_path):
    legacy = tmp_path / "metatron.db"
    _seed_legacy(legacy)
    cat = Catalog(str(tmp_path / "data"))
    migrated = migrate_legacy_db(legacy, cat)
    assert migrated is True
    store = CatalogDecisionStore(cat)
    assert store.list_repos() == ["repoA", "repoB"]
    assert [p.pattern for p in store.list(repo="repoA")] == ["p-repoA"]
    assert not legacy.exists()
    assert list(tmp_path.glob("metatron.db.migrated-*"))   # archived


def test_migrate_is_idempotent(tmp_path):
    legacy = tmp_path / "metatron.db"; _seed_legacy(legacy)
    cat = Catalog(str(tmp_path / "data"))
    assert migrate_legacy_db(legacy, cat) is True
    assert migrate_legacy_db(legacy, cat) is False   # nothing left to do
```

- [ ] **Step 2 — run, expect fail.**

- [ ] **Step 3 — implement** `metatron/storage/migrate.py`:

```python
"""One-time split of a legacy single ``metatron.db`` into per-repo catalog files."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from metatron.storage.catalog import Catalog
from metatron.storage.sqlite import (
    SQLiteEventStore,
    SQLiteIngestRunStore,
    SQLiteDecisionStore,
)


def migrate_legacy_db(legacy_path: str | Path, catalog: Catalog) -> bool:
    """Copy each repo's rows from ``legacy_path`` into its catalog file, then archive.

    Idempotent: returns ``False`` (no-op) once the legacy file is gone/archived. The
    copy goes through the stores (read filtered by repo, write into the new file), so
    it stays schema-safe. Re-running after an interruption re-copies until the final
    archive rename succeeds.
    """
    legacy = Path(legacy_path)
    if not legacy.is_file():
        return False

    decisions = SQLiteDecisionStore(str(legacy))
    events = SQLiteEventStore(str(legacy))
    runs = SQLiteIngestRunStore(str(legacy))
    try:
        for repo in decisions.list_repos():
            dst = catalog.open(repo)
            for p in decisions.list(repo=repo):
                dst.decisions.add(p)
            for e in events.list_events(repo=repo):
                dst.events.record(e)
            for r in runs.list_for_repo(repo):
                dst.runs.record(r)
    finally:
        decisions.close(); events.close(); runs.close()

    archive = legacy.with_name(f"{legacy.name}.migrated-{date.today().isoformat()}")
    legacy.rename(archive)
    return True
```

- [ ] **Step 4 — run, expect pass.** **Step 5 — full suite.** **Step 6 — commit:**

```bash
git add metatron/storage/migrate.py tests/test_migrate.py
git commit -m "storage: one-time auto-split migration of legacy metatron.db"
```

---

## Task 4 (PR #4): Cut `cli.main()` over to the catalog

**Files:**
- Modify: `metatron/config.py`, `metatron/cli.py`
- Test: extend `tests/test_cli.py`; add `tests/test_cli_catalog_e2e.py`

- [ ] **Step 1 — config default to home catalog** (`metatron/config.py`): change `DEFAULT_DB_PATH` and add a data-dir constant:

```python
from pathlib import Path
DEFAULT_DB_PATH = str(Path.home() / ".metatron")
```

(Keep the `METATRON_DB` env / `db_path` toml overrides exactly as-is — they now name a directory or a single file.)

- [ ] **Step 2 — failing e2e test** (`tests/test_cli_catalog_e2e.py`): drive `main()` with a catalog dir via `METATRON_DB`, ingest-free, by injecting catalog stores; assert two ingested repos produce two `.db` files and that `serve`-side resolution sees only the chosen repo. Minimal version:

```python
from metatron.config import Settings
from metatron.storage.catalog import Catalog, CatalogDecisionStore
from metatron.cli import _resolve_repo


def test_resolve_repo_uses_catalog_listing(tmp_path):
    cat = Catalog(str(tmp_path))
    store = CatalogDecisionStore(cat)
    from metatron.models import Origin, Decision, Status
    store.add(Decision(repo="only/repo", pattern="p", scope="a", rationale="r",
                    origin=Origin.BOOTSTRAP, status=Status.CANONICAL))
    # sole repo in the catalog → resolved with no flags
    assert _resolve_repo(None, store, Settings()) == "only/repo"
```

- [ ] **Step 3 — wire `main()`** (`metatron/cli.py`). Replace the construction at lines ~108-110 and the per-command default stores so the catalog is the source of truth:

```python
from metatron.storage.catalog import (
    Catalog, CatalogDecisionStore, CatalogEventStore, CatalogIngestRunStore,
)
from metatron.storage.migrate import migrate_legacy_db

settings = load_settings()
catalog = Catalog(settings.db_path)
# One-time split of a legacy cwd metatron.db into the catalog (no-op afterwards).
migrate_legacy_db("metatron.db", catalog)

if store is None:
    store = CatalogDecisionStore(catalog)
event_store = event_store or CatalogEventStore(catalog)
run_store = run_store or CatalogIngestRunStore(catalog)
```

Then simplify the call sites to pass `event_store` / `run_store` directly (they are no longer `None`), e.g. `_cmd_serve(store, _resolve_repo(args.repo, store, settings), event_store)` and likewise for `ui`, `ingest`, `refine-feedback`. `_resolve_repo` itself is unchanged. Single-file mode is automatic: `METATRON_DB=/path/received.db` makes `Catalog` a single-file catalog, so the recipient's `metatron --db received.db ui` resolves the lone repo.

- [ ] **Step 4 — add a `--db` global flag** (optional convenience mirroring `METATRON_DB`). In `_build_parser`, add `parser.add_argument("--db")`; in `main`, if `args.db`, set `settings = settings.model_copy(update={"db_path": args.db})` before building the catalog. Test that `--db <file>` enters single-file mode.

- [ ] **Step 5 — run, expect pass:** `uv run -m pytest tests/test_cli.py tests/test_cli_catalog_e2e.py -q`.

- [ ] **Step 6 — full suite** `uv run -m pytest -q`. Fix any test that hard-coded a single `metatron.db` path; tests that inject `store=`/`event_store=` keep working since `main()` honors injected stores.

- [ ] **Step 7 — manual smoke** (no API key needed): build a catalog with two repos in a temp dir, run `uv run metatron --db <tmp> candidates list --repo <id>` and `serve` handshake; confirm only that repo's decisions appear.

- [ ] **Step 8 — commit:**

```bash
git add metatron/config.py metatron/cli.py tests/test_cli.py tests/test_cli_catalog_e2e.py
git commit -m "cli: route all commands through the per-repo catalog (+ --db, migration)"
```

---

## Task 5 (PR #5): `metatron export <repo>`

**Files:**
- Modify: `metatron/cli.py`
- Test: `tests/test_cli_export.py`

- [ ] **Step 1 — failing test** (`tests/test_cli_export.py`):

```python
from metatron.storage.catalog import Catalog, CatalogDecisionStore
from metatron.cli import _cmd_export
from metatron.models import Origin, Decision, Status


def test_export_copies_repo_file_and_is_openable_single_file(tmp_path, capsys):
    cat = Catalog(str(tmp_path / "data"))
    CatalogDecisionStore(cat).add(Decision(repo="acme/app", pattern="ship me", scope="a",
                                     rationale="r", origin=Origin.BOOTSTRAP,
                                     status=Status.CANONICAL))
    out = tmp_path / "app.db"
    rc = _cmd_export(cat, repo="acme/app", out=str(out), out_stream=capsys)  # see step 3 sig
    assert rc == 0 and out.exists()
    # opens in single-file mode and serves the same decision
    recip = CatalogDecisionStore(Catalog(str(out)))
    assert recip.list_repos() == ["acme/app"]
    assert [p.pattern for p in recip.list(repo="acme/app")] == ["ship me"]
```

- [ ] **Step 2 — run, expect fail.**

- [ ] **Step 3 — implement** `_cmd_export` + parser entry (`metatron/cli.py`). Use sqlite's backup API (consistent snapshot) then `VACUUM`:

```python
import sqlite3
from pathlib import Path

def _cmd_export(catalog, repo, out, out_stream) -> int:
    src = catalog.path_for(repo)
    if not Path(src).exists() or repo not in catalog.list_repos():
        print(f"No data for repo '{repo}'.", file=out_stream)
        return 2
    dst = Path(out or f"{repo.rstrip('/').split('/')[-1]}.db")
    s = sqlite3.connect(src); d = sqlite3.connect(dst)
    try:
        s.backup(d)            # consistent copy of the whole per-repo file
        d.execute("VACUUM")
    finally:
        s.close(); d.close()
    print(f"Exported '{repo}' → {dst}", file=out_stream)
    print(f"Recipient: metatron --db {dst} ui", file=out_stream)
    return 0
```

Parser: add `exp = sub.add_parser("export", help="copy a repo's DB out for hand-off")`, `exp.add_argument("repo")`, `exp.add_argument("--out")`. Dispatch in `main`: `if args.command == "export": return _cmd_export(catalog, _resolve_repo(args.repo, store, settings), args.out, out)` — note `export` accepts an explicit repo positionally; if you prefer `--repo` semantics, resolve accordingly.

- [ ] **Step 4 — run, expect pass.** **Step 5 — full suite.**

- [ ] **Step 6 — docs:** add an "Exporting / sharing a repo" snippet to `README.md` (the export command + recipient single-file usage).

- [ ] **Step 7 — commit:**

```bash
git add metatron/cli.py tests/test_cli_export.py README.md
git commit -m "cli: add 'metatron export <repo>' for hand-off + README usage"
```

---

## Done / acceptance

- Ingesting two repos yields two `~/.metatron/<slug>.db` files; `metatron candidates list` / `ui` / `serve --repo X` behave exactly as before.
- A legacy `metatron.db` is auto-split on first run and archived; second run is a no-op.
- `metatron export <repo> --out app.db` produces a file that a recipient opens with `metatron --db app.db ui|serve` with no `--repo` flag and no MCP setup.
- Full suite green via `uv run -m pytest -q`.
- Each task shipped as its own small PR with tests (per CLAUDE.md).
