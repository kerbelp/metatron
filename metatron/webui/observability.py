"""Pure usage-summary computation over recorded events.

Takes a list of events and returns a JSON-able usage report. Pure (no store, no
IO) so it's directly testable; the web layer fetches events and calls this.
"""

from __future__ import annotations

from collections import Counter

from metatron.events import Event, EventKind


def usage_summary(events: list[Event]) -> dict:
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
    }
