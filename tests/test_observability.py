"""Tests for the pure usage-summary computation."""

from datetime import datetime, timedelta, timezone

from metatron.events import Event, EventKind
from metatron.webui.observability import growth_series, usage_summary


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


# ---------- daily series (the impact-view sparklines) ----------

NOW = datetime(2024, 3, 20, 12, 0, tzinfo=timezone.utc)


def _q_on(day_offset, count):
    return Event(
        repo="r", kind=EventKind.QUERY, area="app", result_count=count,
        timestamp=NOW - timedelta(days=day_offset),
    )


def _fb_on(day_offset, helpful, unhelpful):
    return Event(
        repo="r", kind=EventKind.FEEDBACK, area="app",
        helpful_decision_ids=[f"h{i}" for i in range(helpful)],
        unhelpful_decision_ids=[f"u{i}" for i in range(unhelpful)],
        timestamp=NOW - timedelta(days=day_offset),
    )


def test_daily_series_empty_events_is_all_zeroes():
    s = usage_summary([], now=NOW)
    d = s["daily"]
    for key in ("queries", "coverage", "helpful_rate", "served"):
        assert d[key] == [0] * 14, key


def test_daily_series_buckets_queries_by_utc_day_oldest_first():
    s = usage_summary([_q_on(0, 1), _q_on(0, 2), _q_on(13, 1)], now=NOW)
    d = s["daily"]
    assert d["queries"][0] == 1   # oldest bucket
    assert d["queries"][-1] == 2  # today
    assert sum(d["queries"]) == 3


def test_daily_coverage_is_per_day_hit_rate():
    # day with one hit and one miss -> 0.5; empty days stay 0
    s = usage_summary([_q_on(0, 3), _q_on(0, 0)], now=NOW)
    assert s["daily"]["coverage"][-1] == 0.5
    assert s["daily"]["coverage"][0] == 0


def test_daily_served_is_cumulative_and_includes_pre_window_baseline():
    events = [_q_on(20, 5), _q_on(13, 2), _q_on(0, 3)]
    served = usage_summary(events, now=NOW)["daily"]["served"]
    assert served[0] == 7          # pre-window 5 + oldest-day 2
    assert served[-1] == 10        # ends at the all-time total
    assert served == sorted(served)  # cumulative never decreases


def test_daily_helpful_rate_from_feedback_events():
    s = usage_summary([_fb_on(0, 3, 1)], now=NOW)
    assert s["daily"]["helpful_rate"][-1] == 0.75
    assert s["daily"]["helpful_rate"][0] == 0


def test_old_events_do_not_leak_into_daily_buckets():
    s = usage_summary([_q_on(30, 4)], now=NOW)
    assert s["daily"]["queries"] == [0] * 14


# ---------- knowledge growth (canonical decisions over time) ----------

def _canonical(day_offset):
    from metatron.models import Decision, Origin

    return Decision(
        repo="r", pattern="p", scope="s", rationale="why",
        origin=Origin.BOOTSTRAP,
        updated_at=NOW - timedelta(days=day_offset),
    )


def test_growth_series_empty_is_all_zeroes():
    assert growth_series([], now=NOW) == [0] * 14


def test_growth_series_is_cumulative_with_pre_window_baseline():
    g = growth_series([_canonical(30), _canonical(5), _canonical(0)], now=NOW)
    assert g[0] == 1               # the pre-window decision
    assert g[-1] == 3              # ends at the current total
    assert g == sorted(g)
