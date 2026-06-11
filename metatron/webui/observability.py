"""Pure usage-summary computation over recorded events.

Takes a list of events and returns a JSON-able usage report. Pure (no store, no
IO) so it's directly testable; the web layer fetches events and calls this.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

from metatron.events import Event, EventKind

# The impact-view sparklines cover a fixed two-week window: long enough to show a
# trend, short enough that every bucket fits a small chart.
SERIES_DAYS = 14


def usage_summary(
    events: list[Event], *, now: datetime | None = None, days: int = SERIES_DAYS
) -> dict:
    queries = [e for e in events if e.kind is EventKind.QUERY]
    submissions = [e for e in events if e.kind is EventKind.SUBMIT]

    total = len(queries)
    hits = sum(1 for e in queries if e.result_count > 0)
    misses = total - hits
    avg_results = (sum(e.result_count for e in queries) / total) if total else 0
    coverage_rate = (hits / total) if total else 0

    scope_counts = Counter(e.area or "(global)" for e in queries)
    top_scopes = [
        {"scope": scope, "count": count}
        for scope, count in scope_counts.most_common(10)
    ]

    return {
        "total_queries": total,
        "total_submissions": len(submissions),
        "hits": hits,
        "misses": misses,
        "coverage_rate": round(coverage_rate, 3),
        "avg_results": round(avg_results, 2),
        "top_scopes": top_scopes,
        "daily": _daily_series(events, now=now, days=days),
    }


def growth_series(
    decisions: list, *, now: datetime | None = None, days: int = SERIES_DAYS
) -> list[int]:
    """Cumulative decision count per day, oldest bucket first.

    Buckets by ``updated_at``: approval bumps it, so for canonical decisions it
    approximates "became canonical at" (a later edit shifts that point — accepted).
    Decisions older than the window seed the first bucket, so the series always
    ends at the current total and never invents a trend that didn't happen.
    """
    per_day = [0] * days
    baseline = 0
    today = (now or datetime.now(timezone.utc)).date()
    for d in decisions:
        idx = days - 1 - (today - d.updated_at.date()).days
        if idx < 0:
            baseline += 1
        elif idx < days:
            per_day[idx] += 1
    return _cumulative(per_day, baseline)


def _daily_series(
    events: list[Event], *, now: datetime | None = None, days: int = SERIES_DAYS
) -> dict:
    """Per-day series for the impact sparklines, oldest bucket first.

    All-zero input yields all-zero (flat) series. ``served`` is cumulative and
    seeded with the pre-window total so its last point matches the all-time count.
    """
    today = (now or datetime.now(timezone.utc)).date()

    queries = [0] * days
    query_hits = [0] * days
    served_per_day = [0] * days
    served_baseline = 0
    fb_helpful = [0] * days
    fb_total = [0] * days

    for e in events:
        idx = days - 1 - (today - e.timestamp.date()).days
        if idx >= days:
            continue  # future-dated event (clock skew): ignore rather than misfile
        if e.kind is EventKind.QUERY:
            if idx < 0:
                served_baseline += e.result_count
                continue
            queries[idx] += 1
            query_hits[idx] += 1 if e.result_count > 0 else 0
            served_per_day[idx] += e.result_count
        elif e.kind is EventKind.FEEDBACK and idx >= 0:
            fb_helpful[idx] += len(e.helpful_decision_ids)
            fb_total[idx] += len(e.helpful_decision_ids) + len(e.unhelpful_decision_ids)

    return {
        "queries": queries,
        "coverage": [round(h / q, 3) if q else 0 for h, q in zip(query_hits, queries)],
        "helpful_rate": [
            round(h / t, 3) if t else 0 for h, t in zip(fb_helpful, fb_total)
        ],
        "served": _cumulative(served_per_day, served_baseline),
    }


def _cumulative(per_day: list[int], baseline: int) -> list[int]:
    out, running = [], baseline
    for v in per_day:
        running += v
        out.append(running)
    return out
