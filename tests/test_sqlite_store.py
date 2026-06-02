"""Tests for the storage interface and its SQLite implementation.

These exercise the behaviour through the ``PriorStore`` interface so the same
suite would apply to a future Postgres implementation.
"""

import pytest

from metatron.models import (
    Confidence,
    Origin,
    Prior,
    SourceRef,
    SourceRefKind,
    Status,
)
from metatron.storage.base import PriorStore
from metatron.storage.sqlite import SQLitePriorStore


@pytest.fixture
def store() -> SQLitePriorStore:
    s = SQLitePriorStore(":memory:")
    yield s
    s.close()


def _prior(**overrides) -> Prior:
    fields = dict(
        repo="github.com/acme/app",
        pattern="Use the repository pattern for DB access",
        scope="metatron/storage",
        rationale="Keeps SQL out of callers",
        origin=Origin.BOOTSTRAP,
    )
    fields.update(overrides)
    return Prior(**fields)


def test_sqlite_store_is_a_prior_store(store):
    assert isinstance(store, PriorStore)


def test_search_matches_pattern_and_rationale_case_insensitively(store):
    store.add(_prior(pattern="Keep review output positive: emit Highlights only",
                     rationale="avoid disparaging listed apps", scope="src/review"))
    store.add(_prior(pattern="Gate dashboard access via Clerk",
                     rationale="auth", scope="src/dashboard"))

    by_pattern = store.list(search="highlights")
    assert [p.scope for p in by_pattern] == ["src/review"]

    by_rationale = store.list(search="DISPARAGING")  # case-insensitive
    assert [p.scope for p in by_rationale] == ["src/review"]

    assert store.count(search="clerk") == 1
    assert store.count(search="nonexistent term") == 0


def test_search_combines_with_other_filters(store):
    store.add(_prior(pattern="positive review highlights", scope="a", status=Status.CANONICAL))
    store.add(_prior(pattern="positive review highlights", scope="b", status=Status.CANDIDATE))

    results = store.list(search="highlights", status=Status.CANONICAL)
    assert [p.scope for p in results] == ["a"]


def test_prior_store_is_abstract():
    with pytest.raises(TypeError):
        PriorStore()  # type: ignore[abstract]


def test_add_then_get_round_trips_all_fields(store):
    prior = _prior(
        confidence=Confidence.HIGH,
        status=Status.CANONICAL,
        source_refs=[
            SourceRef(kind=SourceRefKind.FILE, ref="metatron/storage/sqlite.py"),
            SourceRef(kind=SourceRefKind.COMMIT, ref="abc123", detail="introduced"),
        ],
    )
    store.add(prior)

    loaded = store.get(prior.id)
    assert loaded == prior


def test_get_missing_returns_none(store):
    assert store.get("does-not-exist") is None


def test_list_returns_all_added(store):
    a, b = _prior(), _prior()
    store.add(a)
    store.add(b)
    ids = {p.id for p in store.list()}
    assert ids == {a.id, b.id}


def test_list_filters_by_status(store):
    candidate = _prior(status=Status.CANDIDATE)
    canonical = _prior(status=Status.CANONICAL)
    store.add(candidate)
    store.add(canonical)

    result = store.list(status=Status.CANONICAL)
    assert [p.id for p in result] == [canonical.id]


def test_list_filters_by_scope(store):
    storage = _prior(scope="metatron/storage")
    parsing = _prior(scope="metatron/parsing")
    store.add(storage)
    store.add(parsing)

    result = store.list(scope="metatron/parsing")
    assert [p.id for p in result] == [parsing.id]


def test_set_status_updates_status_and_touches_updated_at(store):
    prior = _prior(status=Status.CANDIDATE)
    store.add(prior)

    updated = store.set_status(prior.id, Status.CANONICAL)

    assert updated.status is Status.CANONICAL
    assert updated.updated_at >= prior.updated_at
    # Persisted, not just returned.
    assert store.get(prior.id).status is Status.CANONICAL


def test_set_status_on_missing_id_raises(store):
    with pytest.raises(KeyError):
        store.set_status("nope", Status.CANONICAL)
