"""SQLite implementation of :class:`DecisionStore`.

The schema uses portable column types (TEXT/JSON-as-text) and keeps all SQL
inside this module, so swapping in Postgres later is a matter of adding another
``DecisionStore`` implementation rather than touching callers.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from metatron.events import Event
from metatron.models import IngestRun, Decision, Status
from metatron.storage.base import EventStore, DecisionStore

# Every per-repo file carries this one-row table so it is self-describing (its repo
# id travels inside the file, independent of filename). Defined here and created by
# all three stores so a file opened directly always has it; the Catalog populates it.
_REPO_META_SCHEMA = "CREATE TABLE IF NOT EXISTS repo_meta (repo_id TEXT NOT NULL)"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS decisions (
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


def _table_exists(conn, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def _rename_legacy_table(conn, old: str, new: str) -> None:
    """Rename a pre-'decisions' table (the priors->decisions terminology change)."""
    if _table_exists(conn, old) and not _table_exists(conn, new):
        conn.execute(f"ALTER TABLE {old} RENAME TO {new}")


def _rename_legacy_column(conn, table: str, old: str, new: str) -> None:
    """Rename a legacy *_prior_ids column to *_decision_ids if the old one survives."""
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if old in existing and new not in existing:
        conn.execute(f"ALTER TABLE {table} RENAME COLUMN {old} TO {new}")


def connect(path: str) -> sqlite3.Connection:
    """Open a connection configured for safe concurrent, multi-process access.

    Several processes share each per-repo file at once: every running
    ``metatron serve`` plus ``metatron ui`` and CLI commands. Two pragmas make
    that safe:

    * ``journal_mode=WAL`` — readers and writers no longer block each other, so a
      live ``get_decisions_for_context`` read can't stall a ``submit_*`` write.
    * ``busy_timeout`` — a writer that still hits a contended lock waits instead
      of failing immediately with "database is locked" / "attempt to write a
      readonly database".

    ``isolation_level=None`` runs the connection in **autocommit** mode, and this
    is load-bearing for the live UI, not a style choice. In the default (legacy)
    mode the driver opens an implicit transaction before the first write and holds
    it until the next ``commit()``. That transaction is connection-global, and the
    ``metatron ui`` process shares each connection between the request-serving
    thread and the background job threads (ingest/valuate/feedback-loop). A job
    that opened an implicit transaction would pin the connection to a single WAL
    read snapshot, so every later UI read returned data frozen at that instant —
    the "Knowledge in flight / real-time doesn't update" bug — while other
    processes' writes (a running ``metatron serve``) sailed past unseen. In
    autocommit mode no implicit transaction is ever held across statements, so each
    read sees the latest committed state from every process. Every write here is a
    single statement, so we rely on no multi-statement atomicity; the explicit
    ``commit()`` calls in the stores become harmless no-ops.

    ``check_same_thread=False`` lets the web server share a store created elsewhere
    and lets the background job threads use it. (WAL and autocommit are no-ops for
    ``:memory:`` databases, which is fine.)
    """
    conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


class SQLiteDecisionStore(DecisionStore):
    def __init__(self, path: str = "metatron.db") -> None:
        self.path = path
        self._conn = connect(path)
        # Migrate the legacy 'priors' table name (the priors->decisions rename).
        _rename_legacy_table(self._conn, "priors", "decisions")
        self._conn.execute(_SCHEMA)
        self._conn.execute(_REPO_META_SCHEMA)
        _ensure_column(self._conn, "decisions", "repo", "repo TEXT NOT NULL DEFAULT ''")
        _ensure_column(self._conn, "decisions", "model", "model TEXT NOT NULL DEFAULT ''")
        _ensure_column(self._conn, "decisions", "created_version", "created_version TEXT NOT NULL DEFAULT ''")
        _ensure_column(self._conn, "decisions", "triage", "triage TEXT NOT NULL DEFAULT 'none'")
        _ensure_column(self._conn, "decisions", "triage_reason", "triage_reason TEXT NOT NULL DEFAULT ''")
        self._conn.commit()

    def add(self, decision: Decision) -> Decision:
        row = _to_row(decision)
        placeholders = ", ".join("?" for _ in _COLUMNS)
        self._conn.execute(
            f"INSERT INTO decisions ({', '.join(_COLUMNS)}) VALUES ({placeholders})",
            [row[col] for col in _COLUMNS],
        )
        self._conn.commit()
        return decision

    def get(self, decision_id: str) -> Decision | None:
        cur = self._conn.execute("SELECT * FROM decisions WHERE id = ?", (decision_id,))
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
    ) -> list[Decision]:
        where, params = _filter(repo, status, scope, model, triage, origin, search)
        sql = f"SELECT * FROM decisions{where} ORDER BY created_at DESC, id"
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
        cur = self._conn.execute(f"SELECT COUNT(*) FROM decisions{where}", params)
        return cur.fetchone()[0]

    def list_repos(self) -> list[str]:
        cur = self._conn.execute("SELECT DISTINCT repo FROM decisions ORDER BY repo")
        return [row[0] for row in cur.fetchall()]

    def set_status(self, decision_id: str, status: Status) -> Decision:
        decision = self.get(decision_id)
        if decision is None:
            raise KeyError(decision_id)
        now = datetime.now(timezone.utc)
        updated = decision.model_copy(update={"status": status, "updated_at": now})
        self._conn.execute(
            "UPDATE decisions SET status = ?, updated_at = ? WHERE id = ?",
            (updated.status.value, updated.updated_at.isoformat(), decision_id),
        )
        self._conn.commit()
        return updated

    def set_triage(self, decision_id: str, verdict, reason: str) -> Decision:
        decision = self.get(decision_id)
        if decision is None:
            raise KeyError(decision_id)
        updated = decision.model_copy(update={"triage": verdict, "triage_reason": reason})
        self._conn.execute(
            "UPDATE decisions SET triage = ?, triage_reason = ? WHERE id = ?",
            (updated.triage.value, reason, decision_id),
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
    decision_ids    TEXT NOT NULL,
    version            TEXT NOT NULL DEFAULT '',
    actor_id           TEXT NOT NULL DEFAULT '',
    actor_email        TEXT NOT NULL DEFAULT '',
    actor_name         TEXT NOT NULL DEFAULT '',
    query_ref          TEXT NOT NULL DEFAULT '',
    helpful_decision_ids   TEXT NOT NULL DEFAULT '[]',
    unhelpful_decision_ids TEXT NOT NULL DEFAULT '[]',
    ratings            TEXT NOT NULL DEFAULT '{}',
    missing            TEXT NOT NULL DEFAULT '',
    handled            INTEGER NOT NULL DEFAULT 0
)
"""

_EVENT_COLUMNS = (
    "id", "timestamp", "repo", "kind", "area", "task", "result_count", "decision_ids",
    "version", "actor_id", "actor_email", "actor_name",
    "query_ref", "helpful_decision_ids", "unhelpful_decision_ids", "ratings",
    "missing", "handled",
)

# Event columns persisted as JSON (lists, and the ratings decision_id->score map).
_EVENT_JSON_COLUMNS = ("decision_ids", "helpful_decision_ids", "unhelpful_decision_ids", "ratings")


class SQLiteEventStore(EventStore):
    def __init__(self, path: str = "metatron.db") -> None:
        self.path = path
        self._conn = connect(path)
        self._conn.execute(_EVENTS_SCHEMA)
        self._conn.execute(_REPO_META_SCHEMA)
        # Migrate legacy *_prior_ids columns (the priors->decisions rename).
        _rename_legacy_column(self._conn, "events", "prior_ids", "decision_ids")
        _rename_legacy_column(self._conn, "events", "helpful_prior_ids", "helpful_decision_ids")
        _rename_legacy_column(self._conn, "events", "unhelpful_prior_ids", "unhelpful_decision_ids")
        _ensure_column(self._conn, "events", "repo", "repo TEXT NOT NULL DEFAULT ''")
        _ensure_column(self._conn, "events", "version", "version TEXT NOT NULL DEFAULT ''")
        _ensure_column(self._conn, "events", "actor_id", "actor_id TEXT NOT NULL DEFAULT ''")
        _ensure_column(self._conn, "events", "actor_email", "actor_email TEXT NOT NULL DEFAULT ''")
        _ensure_column(self._conn, "events", "actor_name", "actor_name TEXT NOT NULL DEFAULT ''")
        _ensure_column(self._conn, "events", "query_ref", "query_ref TEXT NOT NULL DEFAULT ''")
        _ensure_column(self._conn, "events", "helpful_decision_ids", "helpful_decision_ids TEXT NOT NULL DEFAULT '[]'")
        _ensure_column(self._conn, "events", "unhelpful_decision_ids", "unhelpful_decision_ids TEXT NOT NULL DEFAULT '[]'")
        _ensure_column(self._conn, "events", "ratings", "ratings TEXT NOT NULL DEFAULT '{}'")
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
            "UPDATE events SET handled = 1, decision_ids = ? WHERE id = ?",
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
    decisions_created INTEGER NOT NULL,
    input_tokens   INTEGER NOT NULL,
    output_tokens  INTEGER NOT NULL
)
"""

_RUN_COLUMNS = (
    "id", "repo", "model", "timestamp", "files_parsed", "commits_read",
    "scopes", "decisions_created", "input_tokens", "output_tokens",
)


class SQLiteIngestRunStore:
    def __init__(self, path: str = "metatron.db") -> None:
        self.path = path
        self._conn = connect(path)
        self._conn.execute(_RUNS_SCHEMA)
        self._conn.execute(_REPO_META_SCHEMA)
        # Migrate the legacy priors_created column (the priors->decisions rename).
        _rename_legacy_column(self._conn, "ingest_runs", "priors_created", "decisions_created")
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


def _to_row(decision: Decision) -> dict:
    data = decision.model_dump(mode="json")
    data["source_refs"] = json.dumps(data["source_refs"])
    return data


def _from_row(row: sqlite3.Row) -> Decision:
    data = dict(row)
    data["source_refs"] = json.loads(data["source_refs"])
    return Decision.model_validate(data)
