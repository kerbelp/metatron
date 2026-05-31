"""Tests for ordering, pagination (limit/offset), and counting in the store."""

from datetime import datetime, timezone

import pytest

from metatron.models import Origin, Prior, Status
from metatron.storage.sqlite import SQLitePriorStore


@pytest.fixture
def store() -> SQLitePriorStore:
    s = SQLitePriorStore(":memory:")
    yield s
    s.close()


def _prior_at(day: int, **kw) -> Prior:
    kw.setdefault("origin", Origin.BOOTSTRAP)
    kw.setdefault("scope", "app")
    return Prior(
        pattern="p",
        rationale="r",
        created_at=datetime(2024, 1, day, tzinfo=timezone.utc),
        **kw,
    )


def test_list_orders_newest_first(store):
    old = _prior_at(1)
    new = _prior_at(15)
    store.add(old)
    store.add(new)
    assert [p.id for p in store.list()] == [new.id, old.id]


def test_list_limit_and_offset_paginate(store):
    priors = [_prior_at(d) for d in (1, 2, 3)]  # newest is day 3
    for p in priors:
        store.add(p)

    page1 = store.list(limit=2, offset=0)
    page2 = store.list(limit=2, offset=2)

    assert [p.id for p in page1] == [priors[2].id, priors[1].id]
    assert [p.id for p in page2] == [priors[0].id]


def test_count_total_and_filtered(store):
    store.add(_prior_at(1, status=Status.CANDIDATE))
    store.add(_prior_at(2, status=Status.CANONICAL))
    store.add(_prior_at(3, status=Status.CANDIDATE))

    assert store.count() == 3
    assert store.count(status=Status.CANDIDATE) == 2
    assert store.count(status=Status.CANONICAL) == 1


def test_count_respects_scope_filter(store):
    store.add(_prior_at(1, scope="app"))
    store.add(_prior_at(2, scope="lib"))
    assert store.count(scope="lib") == 1
