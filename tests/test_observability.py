"""Tests for the pure usage-summary computation."""

from datetime import datetime, timezone

from metatron.events import Event, EventKind
from metatron.webui.observability import usage_summary


def _q(area, count):
    return Event(
        repo="github.com/acme/app",
        kind=EventKind.QUERY,
        area=area,
        result_count=count,
        timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )


def test_empty_summary_has_safe_zeroes():
    s = usage_summary([])
    assert s["total_queries"] == 0
    assert s["coverage_rate"] == 0
    assert s["avg_results"] == 0
    assert s["top_scopes"] == []


def test_counts_queries_hits_and_misses():
    s = usage_summary([_q("app", 2), _q("app", 0), _q("lib", 3)])
    assert s["total_queries"] == 3
    assert s["hits"] == 2
    assert s["misses"] == 1


def test_coverage_rate_is_hits_over_queries():
    s = usage_summary([_q("a", 1), _q("b", 0), _q("c", 0), _q("d", 5)])
    assert s["coverage_rate"] == 0.5


def test_avg_results_over_queries():
    s = usage_summary([_q("a", 1), _q("b", 3)])
    assert s["avg_results"] == 2.0


def test_top_scopes_ranked_by_query_count():
    events = [_q("app", 1), _q("app", 1), _q("lib", 0)]
    s = usage_summary(events)
    assert s["top_scopes"][0] == {"scope": "app", "count": 2}


def test_submissions_counted_separately_from_queries():
    events = [
        _q("app", 1),
        Event(repo="r", kind=EventKind.SUBMIT, area="app", timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc)),
    ]
    s = usage_summary(events)
    assert s["total_queries"] == 1
    assert s["total_submissions"] == 1
