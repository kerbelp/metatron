"""The priors->decisions rename migrates existing databases in place on open."""

import sqlite3

from metatron.events import Event, EventKind
from metatron.models import Decision, Origin, Status
from metatron.storage.sqlite import SQLiteDecisionStore, SQLiteEventStore


def test_decision_store_migrates_a_legacy_priors_table(tmp_path):
    db = tmp_path / "legacy.db"
    store = SQLiteDecisionStore(str(db))
    d = store.add(Decision(repo="r", pattern="keep me", scope="a", rationale="x",
                           origin=Origin.BOOTSTRAP, status=Status.CANONICAL))
    store.close()

    # Downgrade to the pre-rename table name, as an old DB on disk would have it.
    conn = sqlite3.connect(db)
    conn.execute("ALTER TABLE decisions RENAME TO priors")
    conn.commit()
    conn.close()

    # Reopening migrates priors -> decisions and still reads the row.
    reopened = SQLiteDecisionStore(str(db))
    assert reopened.get(d.id).pattern == "keep me"
    names = {r[0] for r in reopened._conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert "decisions" in names and "priors" not in names


def test_event_store_migrates_legacy_prior_id_columns(tmp_path):
    db = tmp_path / "legacy.db"
    es = SQLiteEventStore(str(db))
    e = es.record(Event(repo="r", kind=EventKind.QUERY, decision_ids=["x"],
                        helpful_decision_ids=["x"], unhelpful_decision_ids=["y"]))
    es.close()

    # Downgrade the three columns to their pre-rename names.
    conn = sqlite3.connect(db)
    conn.execute("ALTER TABLE events RENAME COLUMN decision_ids TO prior_ids")
    conn.execute("ALTER TABLE events RENAME COLUMN helpful_decision_ids TO helpful_prior_ids")
    conn.execute("ALTER TABLE events RENAME COLUMN unhelpful_decision_ids TO unhelpful_prior_ids")
    conn.commit()
    conn.close()

    reopened = SQLiteEventStore(str(db))
    got = reopened.get(e.id)
    assert got.decision_ids == ["x"]
    assert got.helpful_decision_ids == ["x"]
    assert got.unhelpful_decision_ids == ["y"]
