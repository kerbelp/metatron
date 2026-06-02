"""SQLite implementation of :class:`PriorStore`.

The schema uses portable column types (TEXT/JSON-as-text) and keeps all SQL
inside this module, so swapping in Postgres later is a matter of adding another
``PriorStore`` implementation rather than touching callers.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from metatron.events import Event
from metatron.models import IngestRun, Prior, Status
from metatron.storage.base import EventStore, PriorStore

_SCHEMA = """
CREATE TABLE IF NOT EXISTS priors (
    id          TEXT PRIMARY KEY,
    repo        TEXT NOT NULL DEFAULT '',
    pattern     TEXT NOT NULL,
    scope       TEXT NOT NULL,
    rationale   TEXT NOT NULL,
    origin      TEXT NOT NULL,
    confidence  TEXT NOT NULL,
    model       TEXT NOT NULL DEFAULT '',
    created_version TEXT NOT NULL DEFAULT '',
    source_refs TEXT NOT NULL,
    status      TEXT NOT NULL,
    triage        TEXT NOT NULL DEFAULT 'none',
    triage_reason TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
)
"""

_COLUMNS = (
    "id",
    "repo",
    "pattern",
    "scope",
    "rationale",
    "origin",
    "confidence",
    "model",
    "created_version",
    "source_refs",
    "status",
    "triage",
    "triage_reason",
    "created_at",
    "updated_at",
)


def _ensure_column(conn, table: str, column: str, ddl: str) -> None:
    """Add ``column`` to ``table`` if an older database predates it."""
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


class SQLitePriorStore(PriorStore):
    def __init__(self, path: str = "metatron.db") -> None:
        # check_same_thread=False lets the web server (which runs in its own
        # thread) share a store created elsewhere; the UI server is
        # single-threaded, so access stays serialized.
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(_SCHEMA)
        _ensure_column(self._conn, "priors", "repo", "repo TEXT NOT NULL DEFAULT ''")
        _ensure_column(self._conn, "priors", "model", "model TEXT NOT NULL DEFAULT ''")
        _ensure_column(self._conn, "priors", "created_version", "created_version TEXT NOT NULL DEFAULT ''")
        _ensure_column(self._conn, "priors", "triage", "triage TEXT NOT NULL DEFAULT 'none'")
        _ensure_column(self._conn, "priors", "triage_reason", "triage_reason TEXT NOT NULL DEFAULT ''")
        self._conn.commit()

    def add(self, prior: Prior) -> Prior:
        row = _to_row(prior)
        placeholders = ", ".join("?" for _ in _COLUMNS)
        self._conn.execute(
            f"INSERT INTO priors ({', '.join(_COLUMNS)}) VALUES ({placeholders})",
            [row[col] for col in _COLUMNS],
        )
        self._conn.commit()
        return prior

    def get(self, prior_id: str) -> Prior | None:
        cur = self._conn.execute("SELECT * FROM priors WHERE id = ?", (prior_id,))
        row = cur.fetchone()
        return _from_row(row) if row is not None else None

    def list(
        self,
        *,
        repo: str | None = None,
        status: Status | None = None,
        scope: str | None = None,
        model: str | None = None,
        triage: "TriageVerdict | None" = None,
        origin: "Origin | None" = None,
        search: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[Prior]:
        where, params = _filter(repo, status, scope, model, triage, origin, search)
        sql = f"SELECT * FROM priors{where} ORDER BY created_at DESC, id"
        if limit is not None:
            sql += " LIMIT ? OFFSET ?"
            params = [*params, limit, offset]
        cur = self._conn.execute(sql, params)
        return [_from_row(row) for row in cur.fetchall()]

    def count(
        self,
        *,
        repo: str | None = None,
        status: Status | None = None,
        scope: str | None = None,
        model: str | None = None,
        triage: "TriageVerdict | None" = None,
        origin: "Origin | None" = None,
        search: str | None = None,
    ) -> int:
        where, params = _filter(repo, status, scope, model, triage, origin, search)
        cur = self._conn.execute(f"SELECT COUNT(*) FROM priors{where}", params)
        return cur.fetchone()[0]

    def list_repos(self) -> list[str]:
        cur = self._conn.execute("SELECT DISTINCT repo FROM priors ORDER BY repo")
        return [row[0] for row in cur.fetchall()]

    def set_status(self, prior_id: str, status: Status) -> Prior:
        prior = self.get(prior_id)
        if prior is None:
            raise KeyError(prior_id)
        now = datetime.now(timezone.utc)
        updated = prior.model_copy(update={"status": status, "updated_at": now})
        self._conn.execute(
            "UPDATE priors SET status = ?, updated_at = ? WHERE id = ?",
            (updated.status.value, updated.updated_at.isoformat(), prior_id),
        )
        self._conn.commit()
        return updated

    def set_triage(self, prior_id: str, verdict, reason: str) -> Prior:
        prior = self.get(prior_id)
        if prior is None:
            raise KeyError(prior_id)
        updated = prior.model_copy(update={"triage": verdict, "triage_reason": reason})
        self._conn.execute(
            "UPDATE priors SET triage = ?, triage_reason = ? WHERE id = ?",
            (updated.triage.value, reason, prior_id),
        )
        self._conn.commit()
        return updated

    def close(self) -> None:
        self._conn.close()


_EVENTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id           TEXT PRIMARY KEY,
    timestamp    TEXT NOT NULL,
    repo         TEXT NOT NULL DEFAULT '',
    kind         TEXT NOT NULL,
    area         TEXT NOT NULL,
    task         TEXT NOT NULL,
    result_count INTEGER NOT NULL,
    prior_ids    TEXT NOT NULL,
    version            TEXT NOT NULL DEFAULT '',
    query_ref          TEXT NOT NULL DEFAULT '',
    helpful_prior_ids   TEXT NOT NULL DEFAULT '[]',
    unhelpful_prior_ids TEXT NOT NULL DEFAULT '[]',
    missing            TEXT NOT NULL DEFAULT '',
    handled            INTEGER NOT NULL DEFAULT 0
)
"""

_EVENT_COLUMNS = (
    "id", "timestamp", "repo", "kind", "area", "task", "result_count", "prior_ids",
    "version", "query_ref", "helpful_prior_ids", "unhelpful_prior_ids", "missing",
    "handled",
)

# Event columns persisted as JSON-encoded lists.
_EVENT_JSON_COLUMNS = ("prior_ids", "helpful_prior_ids", "unhelpful_prior_ids")


class SQLiteEventStore(EventStore):
    def __init__(self, path: str = "metatron.db") -> None:
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(_EVENTS_SCHEMA)
        _ensure_column(self._conn, "events", "repo", "repo TEXT NOT NULL DEFAULT ''")
        _ensure_column(self._conn, "events", "version", "version TEXT NOT NULL DEFAULT ''")
        _ensure_column(self._conn, "events", "query_ref", "query_ref TEXT NOT NULL DEFAULT ''")
        _ensure_column(self._conn, "events", "helpful_prior_ids", "helpful_prior_ids TEXT NOT NULL DEFAULT '[]'")
        _ensure_column(self._conn, "events", "unhelpful_prior_ids", "unhelpful_prior_ids TEXT NOT NULL DEFAULT '[]'")
        _ensure_column(self._conn, "events", "missing", "missing TEXT NOT NULL DEFAULT ''")
        _ensure_column(self._conn, "events", "handled", "handled INTEGER NOT NULL DEFAULT 0")
        self._conn.commit()

    def record(self, event: Event) -> Event:
        data = event.model_dump(mode="json")
        for col in _EVENT_JSON_COLUMNS:
            data[col] = json.dumps(data[col])
        placeholders = ", ".join("?" for _ in _EVENT_COLUMNS)
        self._conn.execute(
            f"INSERT INTO events ({', '.join(_EVENT_COLUMNS)}) VALUES ({placeholders})",
            [data[col] for col in _EVENT_COLUMNS],
        )
        self._conn.commit()
        return event

    def get(self, event_id: str) -> Event | None:
        cur = self._conn.execute("SELECT * FROM events WHERE id = ?", (event_id,))
        row = cur.fetchone()
        return _event_from_row(row) if row is not None else None

    def unhandled_feedback(self, *, repo: str | None = None) -> list[Event]:
        where = "kind = 'feedback' AND handled = 0"
        params: list = []
        if repo is not None:
            where += " AND repo = ?"
            params.append(repo)
        cur = self._conn.execute(
            f"SELECT * FROM events WHERE {where} ORDER BY timestamp", params
        )
        return [_event_from_row(row) for row in cur.fetchall()]

    def mark_handled(self, event_id: str, produced_ids: list[str]) -> None:
        self._conn.execute(
            "UPDATE events SET handled = 1, prior_ids = ? WHERE id = ?",
            (json.dumps(produced_ids), event_id),
        )
        self._conn.commit()

    def list_events(
        self,
        *,
        repo: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[Event]:
        where = " WHERE repo = ?" if repo is not None else ""
        params: list = [repo] if repo is not None else []
        sql = f"SELECT * FROM events{where} ORDER BY timestamp DESC, id"
        if limit is not None:
            sql += " LIMIT ? OFFSET ?"
            params = [*params, limit, offset]
        cur = self._conn.execute(sql, params)
        return [_event_from_row(row) for row in cur.fetchall()]

    def count_events(self, *, repo: str | None = None) -> int:
        where = " WHERE repo = ?" if repo is not None else ""
        params = [repo] if repo is not None else []
        return self._conn.execute(
            f"SELECT COUNT(*) FROM events{where}", params
        ).fetchone()[0]

    def close(self) -> None:
        self._conn.close()


def _event_from_row(row: sqlite3.Row) -> Event:
    data = dict(row)
    for col in _EVENT_JSON_COLUMNS:
        if col in data and isinstance(data[col], str):
            data[col] = json.loads(data[col])
    return Event.model_validate(data)


_RUNS_SCHEMA = """
CREATE TABLE IF NOT EXISTS ingest_runs (
    id             TEXT PRIMARY KEY,
    repo           TEXT NOT NULL,
    model          TEXT NOT NULL,
    timestamp      TEXT NOT NULL,
    files_parsed   INTEGER NOT NULL,
    commits_read   INTEGER NOT NULL,
    scopes         INTEGER NOT NULL,
    priors_created INTEGER NOT NULL,
    input_tokens   INTEGER NOT NULL,
    output_tokens  INTEGER NOT NULL
)
"""

_RUN_COLUMNS = (
    "id", "repo", "model", "timestamp", "files_parsed", "commits_read",
    "scopes", "priors_created", "input_tokens", "output_tokens",
)


class SQLiteIngestRunStore:
    def __init__(self, path: str = "metatron.db") -> None:
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(_RUNS_SCHEMA)
        self._conn.commit()

    def record(self, run: IngestRun) -> IngestRun:
        data = run.model_dump(mode="json")
        placeholders = ", ".join("?" for _ in _RUN_COLUMNS)
        self._conn.execute(
            f"INSERT INTO ingest_runs ({', '.join(_RUN_COLUMNS)}) VALUES ({placeholders})",
            [data[col] for col in _RUN_COLUMNS],
        )
        self._conn.commit()
        return run

    def list_for_repo(self, repo: str | None) -> list[IngestRun]:
        where = " WHERE repo = ?" if repo is not None else ""
        params = [repo] if repo is not None else []
        cur = self._conn.execute(
            f"SELECT * FROM ingest_runs{where} ORDER BY timestamp DESC, id", params
        )
        return [IngestRun.model_validate(dict(row)) for row in cur.fetchall()]

    def close(self) -> None:
        self._conn.close()


def _filter(
    repo: str | None,
    status: Status | None,
    scope: str | None,
    model: str | None = None,
    triage=None,
    origin=None,
    search: str | None = None,
) -> tuple[str, list]:
    clauses: list[str] = []
    params: list = []
    if repo is not None:
        clauses.append("repo = ?")
        params.append(repo)
    if status is not None:
        clauses.append("status = ?")
        params.append(status.value)
    if scope is not None:
        clauses.append("scope = ?")
        params.append(scope)
    if model is not None:
        clauses.append("model = ?")
        params.append(model)
    if triage is not None:
        clauses.append("triage = ?")
        params.append(triage.value)
    if origin is not None:
        clauses.append("origin = ?")
        params.append(origin.value)
    if search:
        clauses.append("(LOWER(pattern) LIKE ? OR LOWER(rationale) LIKE ?)")
        like = f"%{search.lower()}%"
        params.extend([like, like])
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    return where, params


def _to_row(prior: Prior) -> dict:
    data = prior.model_dump(mode="json")
    data["source_refs"] = json.dumps(data["source_refs"])
    return data


def _from_row(row: sqlite3.Row) -> Prior:
    data = dict(row)
    data["source_refs"] = json.loads(data["source_refs"])
    return Prior.model_validate(data)
