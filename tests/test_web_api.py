"""Tests for the web API logic (pure: store in, JSON-able dicts out)."""

from datetime import datetime, timezone

import pytest

from metatron.models import Origin, Prior, Status
from metatron.storage.sqlite import SQLitePriorStore
from metatron.webui.api import approve, list_priors, reject, stats


@pytest.fixture
def store() -> SQLitePriorStore:
    return SQLitePriorStore(":memory:")


def _add(store, n, **kw) -> list[Prior]:
    out = []
    for i in range(n):
        kw.setdefault("origin", Origin.BOOTSTRAP)
        p = Prior(
            pattern=f"p{i}",
            scope=kw.pop("scope", "app"),
            rationale="r",
            origin=kw.get("origin"),
            status=kw.get("status", Status.CANDIDATE),
            created_at=datetime(2024, 1, 1 + i, tzinfo=timezone.utc),
        )
        store.add(p)
        out.append(p)
    return out


def test_list_priors_paginates_and_reports_totals(store):
    _add(store, 5)

    result = list_priors(store, page=1, page_size=2)

    assert len(result["items"]) == 2
    assert result["page"] == 1
    assert result["page_size"] == 2
    assert result["total"] == 5
    assert result["pages"] == 3


def test_list_priors_second_page_offsets(store):
    priors = _add(store, 3)  # newest first: p2, p1, p0
    result = list_priors(store, page=2, page_size=2)
    assert [item["id"] for item in result["items"]] == [priors[0].id]


def test_list_priors_filters_by_status(store):
    _add(store, 1, status=Status.CANDIDATE)
    _add(store, 1, status=Status.CANONICAL)

    result = list_priors(store, status="canonical")

    assert result["total"] == 1
    assert result["items"][0]["status"] == "canonical"


def test_list_items_are_json_serializable_dicts(store):
    _add(store, 1)
    import json

    result = list_priors(store, page=1, page_size=10)
    json.dumps(result)  # must not raise
    assert result["items"][0]["pattern"] == "p0"


def test_approve_sets_canonical(store):
    p = _add(store, 1)[0]
    result = approve(store, p.id)
    assert result["ok"] is True
    assert store.get(p.id).status is Status.CANONICAL


def test_reject_sets_rejected(store):
    p = _add(store, 1)[0]
    result = reject(store, p.id)
    assert result["ok"] is True
    assert store.get(p.id).status is Status.REJECTED


def test_approve_missing_id_returns_error_not_raise(store):
    result = approve(store, "nope")
    assert result["ok"] is False
    assert "nope" in result["error"] or "not found" in result["error"].lower()


def test_stats_counts_by_status(store):
    _add(store, 2, status=Status.CANDIDATE)
    _add(store, 1, status=Status.CANONICAL)

    result = stats(store)

    assert result["candidate"] == 2
    assert result["canonical"] == 1
    assert result["rejected"] == 0
    assert result["total"] == 3
