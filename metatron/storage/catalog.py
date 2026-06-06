"""The repo catalog: one self-contained SQLite file per repo.

A repo's data (priors, events, ingest runs) lives in its own ``<slug>.db`` inside a
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

from metatron.events import Event
from metatron.models import IngestRun, Prior, Status, TriageVerdict
from metatron.storage.base import EventStore, PriorStore
from metatron.storage.sqlite import (
    SQLiteEventStore,
    SQLiteIngestRunStore,
    SQLitePriorStore,
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
    priors: SQLitePriorStore
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
            if rid and rid not in ids:  # de-dupe a manually copied file
                ids.append(rid)
        return sorted(ids)

    def open(self, repo_id: str) -> RepoStores:
        if repo_id in self._open:
            return self._open[repo_id]
        path = self.path_for(repo_id)
        _ensure_repo_meta(path, repo_id)
        stores = RepoStores(
            SQLitePriorStore(str(path)),
            SQLiteEventStore(str(path)),
            SQLiteIngestRunStore(str(path)),
        )
        self._open[repo_id] = stores
        return stores

    def close(self) -> None:
        for s in self._open.values():
            s.priors.close()
            s.events.close()
            s.runs.close()
        self._open.clear()


class CatalogPriorStore(PriorStore):
    """A :class:`PriorStore` over the catalog: route by repo, fan out when repo is None.

    Repo-scoped calls hit exactly one file. ``repo=None`` listings merge across all
    repos and re-sort newest-first. Id-only operations (``get``/``set_status``/
    ``set_triage``) search files — fine at local single-user scale; the hot
    ``get_priors_for_context`` path is always repo-scoped and stays single-file.
    """

    def __init__(self, catalog: Catalog) -> None:
        self._cat = catalog

    def _p(self, repo_id: str) -> SQLitePriorStore:
        return self._cat.open(repo_id).priors

    def add(self, prior: Prior) -> Prior:
        return self._p(prior.repo).add(prior)

    def list(self, *, repo=None, status=None, scope=None, model=None,
             triage=None, origin=None, search=None, limit=None, offset=0):
        kw = dict(status=status, scope=scope, model=model, triage=triage,
                  origin=origin, search=search)
        if repo is not None:
            return self._p(repo).list(repo=repo, limit=limit, offset=offset, **kw)
        merged: list[Prior] = []
        for rid in self._cat.list_repos():
            merged.extend(self._p(rid).list(repo=rid, **kw))
        merged.sort(key=lambda p: (p.created_at, p.id), reverse=True)
        if limit is not None:
            return merged[offset:offset + limit]
        return merged[offset:]

    def count(self, *, repo=None, status=None, scope=None, model=None,
              triage=None, origin=None, search=None):
        kw = dict(status=status, scope=scope, model=model, triage=triage,
                  origin=origin, search=search)
        if repo is not None:
            return self._p(repo).count(repo=repo, **kw)
        return sum(self._p(rid).count(repo=rid, **kw) for rid in self._cat.list_repos())

    def get(self, prior_id: str) -> Prior | None:
        for rid in self._cat.list_repos():
            hit = self._p(rid).get(prior_id)
            if hit is not None:
                return hit
        return None

    def _owner(self, prior_id: str) -> str:
        for rid in self._cat.list_repos():
            if self._p(rid).get(prior_id) is not None:
                return rid
        raise KeyError(prior_id)

    def set_status(self, prior_id: str, status: Status) -> Prior:
        return self._p(self._owner(prior_id)).set_status(prior_id, status)

    def set_triage(self, prior_id: str, verdict: TriageVerdict, reason: str) -> Prior:
        return self._p(self._owner(prior_id)).set_triage(prior_id, verdict, reason)

    def list_repos(self) -> list[str]:
        return self._cat.list_repos()


class CatalogEventStore(EventStore):
    """An :class:`EventStore` over the catalog (same routing/fan-out discipline)."""

    def __init__(self, catalog: Catalog) -> None:
        self._cat = catalog

    def _e(self, repo_id: str) -> SQLiteEventStore:
        return self._cat.open(repo_id).events

    def record(self, event: Event) -> Event:
        return self._e(event.repo).record(event)

    def get(self, event_id: str) -> Event | None:
        for rid in self._cat.list_repos():
            hit = self._e(rid).get(event_id)
            if hit is not None:
                return hit
        return None

    def unhandled_feedback(self, *, repo=None) -> list[Event]:
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

    def list_events(self, *, repo=None, limit=None, offset=0) -> list[Event]:
        if repo is not None:
            return self._e(repo).list_events(repo=repo, limit=limit, offset=offset)
        merged: list[Event] = []
        for rid in self._cat.list_repos():
            merged.extend(self._e(rid).list_events(repo=rid))
        merged.sort(key=lambda e: (e.timestamp, e.id), reverse=True)
        return merged[offset:offset + limit] if limit is not None else merged[offset:]

    def count_events(self, *, repo=None) -> int:
        if repo is not None:
            return self._e(repo).count_events(repo=repo)
        return sum(self._e(r).count_events(repo=r) for r in self._cat.list_repos())


class CatalogIngestRunStore:
    """Routes ingest-run telemetry to the producing repo's file (fan-out when None)."""

    def __init__(self, catalog: Catalog) -> None:
        self._cat = catalog

    def record(self, run: IngestRun) -> IngestRun:
        return self._cat.open(run.repo).runs.record(run)

    def list_for_repo(self, repo) -> list[IngestRun]:
        if repo is not None:
            return self._cat.open(repo).runs.list_for_repo(repo)
        out: list[IngestRun] = []
        for rid in self._cat.list_repos():
            out.extend(self._cat.open(rid).runs.list_for_repo(rid))
        out.sort(key=lambda r: (r.timestamp, r.id), reverse=True)
        return out
