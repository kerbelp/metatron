"""SQLite implementation of :class:`PriorStore`.

The schema uses portable column types (TEXT/JSON-as-text) and keeps all SQL
inside this module, so swapping in Postgres later is a matter of adding another
``PriorStore`` implementation rather than touching callers.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from metatron.models import Prior, Status
from metatron.storage.base import PriorStore

_SCHEMA = """
CREATE TABLE IF NOT EXISTS priors (
    id          TEXT PRIMARY KEY,
    pattern     TEXT NOT NULL,
    scope       TEXT NOT NULL,
    rationale   TEXT NOT NULL,
    origin      TEXT NOT NULL,
    confidence  TEXT NOT NULL,
    source_refs TEXT NOT NULL,
    status      TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
)
"""

_COLUMNS = (
    "id",
    "pattern",
    "scope",
    "rationale",
    "origin",
    "confidence",
    "source_refs",
    "status",
    "created_at",
    "updated_at",
)


class SQLitePriorStore(PriorStore):
    def __init__(self, path: str = "metatron.db") -> None:
        self._conn = sqlite3.connect(path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(_SCHEMA)
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
        status: Status | None = None,
        scope: str | None = None,
    ) -> list[Prior]:
        clauses: list[str] = []
        params: list[str] = []
        if status is not None:
            clauses.append("status = ?")
            params.append(status.value)
        if scope is not None:
            clauses.append("scope = ?")
            params.append(scope)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        cur = self._conn.execute(f"SELECT * FROM priors{where}", params)
        return [_from_row(row) for row in cur.fetchall()]

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

    def close(self) -> None:
        self._conn.close()


def _to_row(prior: Prior) -> dict:
    data = prior.model_dump(mode="json")
    data["source_refs"] = json.dumps(data["source_refs"])
    return data


def _from_row(row: sqlite3.Row) -> Prior:
    data = dict(row)
    data["source_refs"] = json.loads(data["source_refs"])
    return Prior.model_validate(data)
