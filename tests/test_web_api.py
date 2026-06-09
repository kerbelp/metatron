"""Tests for the web API logic (pure: store in, JSON-able dicts out)."""

from datetime import datetime, timezone

import pytest

from metatron.events import Event, EventKind
from metatron.models import Origin, Decision, Status, TriageVerdict
from metatron.storage.sqlite import SQLiteEventStore, SQLiteDecisionStore
from metatron.webui.api import (
    approve,
    feedback_events,
    ingest_cost,
    leaderboard,
    list_decisions,
    reject,
    stats,
    usage,
    valuate_one,
)


@pytest.fixture
def store() -> SQLiteDecisionStore:
    return SQLiteDecisionStore(":memory:")


def _add(store, n, **kw) -> list[Decision]:
    out = []
    for i in range(n):
        kw.setdefault("origin", Origin.BOOTSTRAP)
        p = Decision(
            repo=kw.pop("repo", "github.com/acme/app"),
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


def test_list_decisions_filters_by_search(store):
    _add(store, 1, scope="keep-me")  # pattern "p0"
    store.add(Decision(repo="github.com/acme/app", pattern="emit Highlights only",
                    scope="src/review", rationale="avoid disparaging apps",
                    origin=Origin.BOOTSTRAP))

    result = list_decisions(store, search="highlights")

    assert result["total"] == 1
    assert result["items"][0]["scope"] == "src/review"
    assert result["search"] == "highlights"


def test_list_decisions_filters_by_origin(store):
    _add(store, 2, origin=Origin.BOOTSTRAP)
    _add(store, 1, origin=Origin.AGENT_FEEDBACK)

    result = list_decisions(store, origin="agent_feedback")

    assert result["total"] == 1
    assert all(it["origin"] == "agent_feedback" for it in result["items"])
    assert result["origin"] == "agent_feedback"


def test_list_decisions_paginates_and_reports_totals(store):
    _add(store, 5)

    result = list_decisions(store, page=1, page_size=2)

    assert len(result["items"]) == 2
    assert result["page"] == 1
    assert result["page_size"] == 2
    assert result["total"] == 5
    assert result["pages"] == 3


def test_list_decisions_second_page_offsets(store):
    decisions = _add(store, 3)  # newest first: p2, p1, p0
    result = list_decisions(store, page=2, page_size=2)
    assert [item["id"] for item in result["items"]] == [decisions[0].id]


def test_list_decisions_filters_by_status(store):
    _add(store, 1, status=Status.CANDIDATE)
    _add(store, 1, status=Status.CANONICAL)

    result = list_decisions(store, status="canonical")

    assert result["total"] == 1
    assert result["items"][0]["status"] == "canonical"


def test_list_items_are_json_serializable_dicts(store):
    _add(store, 1)
    import json

    result = list_decisions(store, page=1, page_size=10)
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


def test_usage_splits_kinds_and_resolves_returned_decisions():
    import json

    store = SQLiteDecisionStore(":memory:")
    decision = Decision(
        repo="r", pattern="use zones", scope="app", rationale="x",
        origin=Origin.BOOTSTRAP, status=Status.CANONICAL,
    )
    store.add(decision)
    events = SQLiteEventStore(":memory:")
    events.record(Event(repo="r", kind=EventKind.QUERY, area="app", task="add section", result_count=1, decision_ids=[decision.id]))
    events.record(Event(repo="r", kind=EventKind.QUERY, area="lib", result_count=0))
    events.record(Event(repo="r", kind=EventKind.SUBMIT, area="app/api", decision_ids=[decision.id]))

    result = usage(events, store)

    assert result["total_queries"] == 2
    assert result["total_submissions"] == 1
    assert len(result["recent_queries"]) == 2
    assert len(result["recent_submissions"]) == 1
    # the query that returned a decision has it resolved (pattern, scope) for the detail view
    q = next(e for e in result["recent_queries"] if e["result_count"] == 1)
    assert q["decisions"][0]["pattern"] == "use zones"
    assert q["decisions"][0]["scope"] == "app"
    json.dumps(result)  # must be serializable


def test_actor_is_exposed_in_usage_and_feedback_streams():
    # Attribution must reach the UI: who produced each query / feedback event.
    store = SQLiteDecisionStore(":memory:")
    events = SQLiteEventStore(":memory:")
    events.record(Event(repo="r", kind=EventKind.QUERY, area="app", result_count=0,
                        actor_id="a1", actor_email="dev@corp.com", actor_name="Dev"))
    events.record(Event(repo="r", kind=EventKind.FEEDBACK, missing="gap",
                        actor_id="a1", actor_email="dev@corp.com", actor_name="Dev"))

    q = usage(events, store)["recent_queries"][0]
    assert q["actor_id"] == "a1" and q["actor_email"] == "dev@corp.com" and q["actor_name"] == "Dev"

    fb = feedback_events(events, store)["events"][0]
    assert fb["actor_id"] == "a1" and fb["actor_email"] == "dev@corp.com" and fb["actor_name"] == "Dev"


def test_get_decision_returns_one_or_none():
    from metatron.webui.api import get_decision
    from metatron.models import Decision

    store = SQLiteDecisionStore(":memory:")
    d = store.add(Decision(repo="r", pattern="p", scope="a", rationale="x",
                           origin=Origin.BOOTSTRAP, status=Status.CANONICAL))
    assert get_decision(store, d.id)["pattern"] == "p"
    assert get_decision(store, "missing") is None


def test_feedback_events_include_ratings():
    # The UI's GapCard renders e.ratings; it must be present (its absence blanked
    # the Feedback Loop screen for repos that had feedback).
    store = SQLiteDecisionStore(":memory:")
    events = SQLiteEventStore(":memory:")
    events.record(Event(repo="r", kind=EventKind.FEEDBACK, missing="gap",
                        ratings={"d1": 9, "d2": 3}))
    ev = feedback_events(events, store)["events"][0]
    assert ev["ratings"] == {"d1": 9, "d2": 3}


def test_feedback_events_filters_by_handled_status():
    store = SQLiteDecisionStore(":memory:")
    events = SQLiteEventStore(":memory:")
    events.record(Event(repo="r", kind=EventKind.FEEDBACK, missing="gap A", handled=False))
    events.record(Event(repo="r", kind=EventKind.FEEDBACK, missing="gap B", handled=True))

    assert len(feedback_events(events, store)["events"]) == 2
    assert len(feedback_events(events, store, status="all")["events"]) == 2

    unhandled = feedback_events(events, store, status="unhandled")["events"]
    assert [e["missing"] for e in unhandled] == ["gap A"]
    assert all(e["handled"] is False for e in unhandled)

    handled = feedback_events(events, store, status="handled")["events"]
    assert [e["missing"] for e in handled] == ["gap B"]
    assert all(e["handled"] is True for e in handled)


def test_feedback_events_produced_decisions_carry_status_and_usefulness():
    store = SQLiteDecisionStore(":memory:")
    refined = Decision(repo="r", pattern="refined rule", scope="app", rationale="why",
                    origin=Origin.AGENT_FEEDBACK, status=Status.CANDIDATE)
    store.add(refined)
    events = SQLiteEventStore(":memory:")
    # the handled feedback that produced the candidate (mark_handled stores produced
    # ids on the feedback event's decision_ids)
    events.record(Event(repo="r", kind=EventKind.FEEDBACK, missing="gap",
                        handled=True, decision_ids=[refined.id]))
    # the produced decision later gets served by a query, then rated helpful once
    events.record(Event(repo="r", kind=EventKind.QUERY, area="app",
                        result_count=1, decision_ids=[refined.id]))
    events.record(Event(repo="r", kind=EventKind.FEEDBACK,
                        helpful_decision_ids=[refined.id], handled=True))

    handled = feedback_events(events, store, status="handled")["events"]
    produced = next(e for e in handled if e["missing"] == "gap")["produced"]
    assert len(produced) == 1
    p = produced[0]
    assert p["status"] == "candidate"
    assert p["rationale"] == "why"
    assert p["served"] == 1
    assert p["helpful"] == 1
    assert p["unhelpful"] == 0


def test_ingest_cost_returns_runs_with_estimated_dollars():
    from metatron.models import IngestRun
    from metatron.storage.sqlite import SQLiteIngestRunStore

    runs = SQLiteIngestRunStore(":memory:")
    runs.record(
        IngestRun(
            repo="r", model="claude-sonnet-4-6",
            input_tokens=1_000_000, output_tokens=1_000_000,
            scopes=5, decisions_created=20,
        )
    )
    result = ingest_cost(runs, repo="r")
    assert len(result["runs"]) == 1
    run = result["runs"][0]
    assert run["model"] == "claude-sonnet-4-6"
    assert run["estimated_cost"] == 18.0  # 1M*$3 + 1M*$15


def test_stats_counts_by_status(store):
    _add(store, 2, status=Status.CANDIDATE)
    _add(store, 1, status=Status.CANONICAL)

    result = stats(store)

    assert result["candidate"] == 2
    assert result["canonical"] == 1
    assert result["rejected"] == 0
    assert result["total"] == 3


# ---- leaderboard ----

REPO = "github.com/acme/app"


def _canonical(store, pattern, scope="app"):
    return store.add(Decision(repo=REPO, pattern=pattern, scope=scope, rationale="r",
                           origin=Origin.BOOTSTRAP, status=Status.CANONICAL))


def _rate(events, decision_id, *scores):
    for s in scores:
        events.record(Event(repo=REPO, kind=EventKind.FEEDBACK, ratings={decision_id: s}))


def test_leaderboard_ranks_most_helpful_and_flags_misleading():
    store, events = SQLiteDecisionStore(":memory:"), SQLiteEventStore(":memory:")
    good = _canonical(store, "the helpful one")
    bad = _canonical(store, "the misleading one")
    _canonical(store, "the unrated one")  # never rated → absent from both lists
    _rate(events, good.id, 9, 10, 8)
    _rate(events, bad.id, 2, 1)            # two low ratings clears the review threshold

    lb = leaderboard(events, store, repo=REPO)

    assert lb["most_helpful"][0]["id"] == good.id
    assert lb["most_helpful"][0]["effect"] == "up"
    assert [r["id"] for r in lb["misleading"]] == [bad.id]
    assert lb["misleading"][0]["effect"] == "down"
    assert lb["review_count"] == 1
    assert lb["rated_total"] == 2  # the unrated canonical decision isn't counted


def test_leaderboard_needs_enough_ratings_before_flagging_misleading():
    # A single low rating is noise, not signal — it must not land in the review queue.
    store, events = SQLiteDecisionStore(":memory:"), SQLiteEventStore(":memory:")
    lonely = _canonical(store, "rated once, badly")
    _rate(events, lonely.id, 1)

    lb = leaderboard(events, store, repo=REPO)

    assert lb["misleading"] == []
    assert lb["review_count"] == 0
    assert lb["most_helpful"][0]["id"] == lonely.id  # still appears in the full ranking


def test_leaderboard_ignores_ratings_for_non_canonical_decisions():
    # A candidate (not yet curated) that somehow has ratings is not served, so it
    # must not appear on the leaderboard.
    store, events = SQLiteDecisionStore(":memory:"), SQLiteEventStore(":memory:")
    cand = store.add(Decision(repo=REPO, pattern="not canonical", scope="app",
                           rationale="r", origin=Origin.BOOTSTRAP))
    _rate(events, cand.id, 9, 9)

    lb = leaderboard(events, store, repo=REPO)

    assert lb["most_helpful"] == [] and lb["rated_total"] == 0


# ---------------------------------------------------------------------------
# valuate_one — single-decision advisory judge
# ---------------------------------------------------------------------------

class _StubJudge:
    """Stands in for DecisionJudge: returns a fixed verdict for each candidate.
    Matches the real contract: dict {decision_id: (verdict, reason)}."""
    def __init__(self, verdict=TriageVerdict.APPROVE, reason="looks canonical"):
        self.verdict, self.reason = verdict, reason
    def evaluate(self, decisions, **kw):
        return {c.id: (self.verdict, self.reason) for c in decisions}


def test_valuate_one_sets_triage(store):
    [d] = _add(store, 1)
    out = valuate_one(store, lambda: object(), d.id, judge_factory=lambda _p: _StubJudge())
    assert out["ok"] is True
    assert out["triage"] == "approve"
    assert store.get(d.id).triage is TriageVerdict.APPROVE
    assert store.get(d.id).triage_reason == "looks canonical"


def test_valuate_one_unconfigured_provider_is_clean_error(store):
    [d] = _add(store, 1)
    out = valuate_one(store, None, d.id)
    assert out["ok"] is False and "provider" in out["error"].lower()


def test_valuate_one_unknown_id(store):
    out = valuate_one(store, lambda: object(), "nope", judge_factory=lambda _p: _StubJudge())
    assert out["ok"] is False and "not found" in out["error"].lower()
