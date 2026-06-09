"""Tests for the storage interface and its SQLite implementation.

These exercise the behaviour through the ``DecisionStore`` interface so the same
suite would apply to a future Postgres implementation.
"""

from datetime import datetime, timedelta, timezone

import pytest

from metatron.models import (
    Confidence,
    Origin,
    Decision,
    SourceRef,
    SourceRefKind,
    Status,
)
from metatron.storage.base import DecisionStore
from metatron.storage.sqlite import SQLiteDecisionStore


@pytest.fixture
def store() -> SQLiteDecisionStore:
    s = SQLiteDecisionStore(":memory:")
    yield s
    s.close()


def _decision(**overrides) -> Decision:
    fields = dict(
        repo="github.com/acme/app",
        pattern="Use the repository pattern for DB access",
        scope="metatron/storage",
        rationale="Keeps SQL out of callers",
        origin=Origin.BOOTSTRAP,
    )
    fields.update(overrides)
    return Decision(**fields)


def test_sqlite_store_is_a_decision_store(store):
    assert isinstance(store, DecisionStore)


def test_search_matches_pattern_and_rationale_case_insensitively(store):
    store.add(_decision(pattern="Keep review output positive: emit Highlights only",
                     rationale="avoid disparaging listed apps", scope="src/review"))
    store.add(_decision(pattern="Gate dashboard access via Clerk",
                     rationale="auth", scope="src/dashboard"))

    by_pattern = store.list(search="highlights")
    assert [p.scope for p in by_pattern] == ["src/review"]

    by_rationale = store.list(search="DISPARAGING")  # case-insensitive
    assert [p.scope for p in by_rationale] == ["src/review"]

    assert store.count(search="clerk") == 1
    assert store.count(search="nonexistent term") == 0


def test_search_combines_with_other_filters(store):
    store.add(_decision(pattern="positive review highlights", scope="a", status=Status.CANONICAL))
    store.add(_decision(pattern="positive review highlights", scope="b", status=Status.CANDIDATE))

    results = store.list(search="highlights", status=Status.CANONICAL)
    assert [p.scope for p in results] == ["a"]


def test_decision_store_is_abstract():
    with pytest.raises(TypeError):
        DecisionStore()  # type: ignore[abstract]


def test_add_then_get_round_trips_all_fields(store):
    decision = _decision(
        confidence=Confidence.HIGH,
        status=Status.CANONICAL,
        source_refs=[
            SourceRef(kind=SourceRefKind.FILE, ref="metatron/storage/sqlite.py"),
            SourceRef(kind=SourceRefKind.COMMIT, ref="abc123", detail="introduced"),
        ],
    )
    store.add(decision)

    loaded = store.get(decision.id)
    assert loaded == decision


def test_get_missing_returns_none(store):
    assert store.get("does-not-exist") is None


def test_list_returns_all_added(store):
    a, b = _decision(), _decision()
    store.add(a)
    store.add(b)
    ids = {p.id for p in store.list()}
    assert ids == {a.id, b.id}


def test_list_returns_newest_first(store):
    # The curation UI relies on this order to show candidates newest-first.
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    old = _decision(status=Status.CANDIDATE, created_at=base)
    mid = _decision(status=Status.CANDIDATE, created_at=base + timedelta(hours=1))
    new = _decision(status=Status.CANDIDATE, created_at=base + timedelta(hours=2))
    # Insert out of chronological order to prove ordering is by created_at, not insertion.
    store.add(mid)
    store.add(old)
    store.add(new)

    result = store.list(status=Status.CANDIDATE)
    assert [p.id for p in result] == [new.id, mid.id, old.id]


def test_list_filters_by_status(store):
    candidate = _decision(status=Status.CANDIDATE)
    canonical = _decision(status=Status.CANONICAL)
    store.add(candidate)
    store.add(canonical)

    result = store.list(status=Status.CANONICAL)
    assert [p.id for p in result] == [canonical.id]


def test_list_filters_by_scope(store):
    storage = _decision(scope="metatron/storage")
    parsing = _decision(scope="metatron/parsing")
    store.add(storage)
    store.add(parsing)

    result = store.list(scope="metatron/parsing")
    assert [p.id for p in result] == [parsing.id]


def test_set_status_updates_status_and_touches_updated_at(store):
    decision = _decision(status=Status.CANDIDATE)
    store.add(decision)

    updated = store.set_status(decision.id, Status.CANONICAL)

    assert updated.status is Status.CANONICAL
    assert updated.updated_at >= decision.updated_at
    # Persisted, not just returned.
    assert store.get(decision.id).status is Status.CANONICAL


def test_set_status_on_missing_id_raises(store):
    with pytest.raises(KeyError):
        store.set_status("nope", Status.CANONICAL)


def test_update_fields_edits_content_only(store):
    d = store.add(_decision(pattern="old", rationale="why", status=Status.CANONICAL))
    out = store.update_fields(d.id, pattern="new", rationale="better")
    assert out.pattern == "new" and out.rationale == "better"
    assert out.scope == d.scope            # untouched
    assert out.status is Status.CANONICAL  # never changed by an edit
    assert out.triage is d.triage          # untouched
    assert out.updated_at >= d.updated_at


def test_update_fields_rejects_unknown_id(store):
    with pytest.raises(KeyError):
        store.update_fields("nope", pattern="x")
