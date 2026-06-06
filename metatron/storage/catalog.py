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
