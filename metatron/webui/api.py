"""Web API logic: pure functions from a store to JSON-able dicts.

Kept independent of the HTTP layer so it can be tested directly. The HTTP handler
in :mod:`metatron.webui.server` is a thin adapter over these.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

from metatron.events import EventKind
from metatron.feedback_score import NEUTRAL, helpfulness_scores
from metatron.models import Origin, Status, TriageVerdict
from metatron.pricing import estimate_cost
from metatron.storage.base import EventStore, DecisionStore
from metatron.version import package_version, version_string
from metatron.webui.observability import usage_summary


def version() -> dict:
    """The version + code revision this server is running (shown in the UI footer)."""
    return {"version": package_version(), "revision": version_string()}


def list_decisions(
    store: DecisionStore,
    *,
    repo: str | None = None,
    status: str | None = None,
    scope: str | None = None,
    triage: str | None = None,
    origin: str | None = None,
    search: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    page = max(1, page)
    page_size = max(1, page_size)
    status_enum = Status(status) if status else None
    triage_enum = TriageVerdict(triage) if triage else None
    origin_enum = Origin(origin) if origin else None
    scope_filter = scope or None
    repo_filter = repo or None
    search_filter = search or None

    common = dict(
        repo=repo_filter, status=status_enum, scope=scope_filter,
        triage=triage_enum, origin=origin_enum, search=search_filter,
    )
    total = store.count(**common)
    items = store.list(**common, limit=page_size, offset=(page - 1) * page_size)
    return {
        "items": [p.model_dump(mode="json") for p in items],
        "page": page,
        "page_size": page_size,
        "total": total,
        "pages": (total + page_size - 1) // page_size,
        "repo": repo,
        "status": status,
        "scope": scope,
        "origin": origin,
        "search": search,
    }


def repos(store: DecisionStore) -> dict:
    return {"repos": store.list_repos()}


def get_decision(store: DecisionStore, decision_id: str) -> dict | None:
    """One decision by id (for opening a rated decision from the feedback view)."""
    decision = store.get(decision_id)
    return decision.model_dump(mode="json") if decision is not None else None


def ingest_cost(run_store, *, repo: str | None = None) -> dict:
    runs = []
    for run in run_store.list_for_repo(repo):
        data = run.model_dump(mode="json")
        data["estimated_cost"] = estimate_cost(
            run.model, run.input_tokens, run.output_tokens
        )
        runs.append(data)
    return {"runs": runs}


def approve(store: DecisionStore, decision_id: str) -> dict:
    return _set_status(store, decision_id, Status.CANONICAL)


def reject(store: DecisionStore, decision_id: str) -> dict:
    return _set_status(store, decision_id, Status.REJECTED)


def approve_recommended(
    store: DecisionStore, *, repo: str | None = None, origin: str | None = None
) -> dict:
    """Promote every candidate the judge marked ``approve`` to canonical, at once.

    This is the one-click "Approve recommended" action: a human triggers it after
    reviewing the valuation, so the human-in-the-loop invariant holds — nothing
    self-promotes, the person decides to accept the recommended batch.

    ``origin`` narrows the batch to one provenance (e.g. ``agent_feedback`` for the
    Feedback screen's button); ``None`` means every recommended candidate in the repo
    (the Decisions screen's button).
    """
    recommended = store.list(
        repo=repo or None,
        status=Status.CANDIDATE,
        triage=TriageVerdict.APPROVE,
        origin=Origin(origin) if origin else None,
    )
    for decision in recommended:
        store.set_status(decision.id, Status.CANONICAL)
    return {"ok": True, "approved": len(recommended)}


def stats(store: DecisionStore, *, repo: str | None = None) -> dict:
    repo_filter = repo or None
    counts = {s.value: store.count(repo=repo_filter, status=s) for s in Status}
    counts["total"] = store.count(repo=repo_filter)
    return counts


def usage(
    event_store: EventStore,
    store: DecisionStore,
    *,
    repo: str | None = None,
    recent: int = 25,
) -> dict:
    repo_filter = repo or None
    events = event_store.list_events(repo=repo_filter)  # newest-first
    summary = usage_summary(events)

    def enrich(event) -> dict:
        data = event.model_dump(mode="json")
        decisions = []
        for decision_id in event.decision_ids:
            decision = store.get(decision_id)
            if decision is not None:
                decisions.append(
                    {
                        "id": decision.id,
                        "pattern": decision.pattern,
                        "scope": decision.scope,
                        "confidence": decision.confidence.value,
                        "rationale": decision.rationale,
                    }
                )
        data["decisions"] = decisions
        return data

    summary["recent_queries"] = [
        enrich(e) for e in events if e.kind is EventKind.QUERY
    ][:recent]
    summary["recent_submissions"] = [
        enrich(e) for e in events if e.kind is EventKind.SUBMIT
    ][:recent]
    return summary


def agent_activity(
    event_store: EventStore,
    store: DecisionStore,
    *,
    repo: str | None = None,
    window_mins: int = 30,
) -> dict:
    """Recent agent activity grouped by the employee (actor) who produced it.

    Uses event attribution: each agent is one actor, with the queries they ran, the
    decisions they were served, and the feedback they sent within the time window. Powers
    the live "agent impact" view — who Metatron is helping right now.
    """
    repo_filter = repo or None
    now = datetime.now(timezone.utc)
    cutoff = now - _timedelta_mins(window_mins)
    recent = [e for e in event_store.list_events(repo=repo_filter) if e.timestamp >= cutoff]

    by_actor: dict[str, list] = {}
    for e in recent:
        key = e.actor_id or e.actor_email or "anonymous"
        by_actor.setdefault(key, []).append(e)

    agents = []
    for key, evs in by_actor.items():
        evs.sort(key=lambda e: e.timestamp, reverse=True)  # newest first
        latest = evs[0]
        queries = [e for e in evs if e.kind is EventKind.QUERY]
        feedback = [e for e in evs if e.kind is EventKind.FEEDBACK]
        sample = next((e for e in queries if e.area), latest)  # a query with context
        agents.append({
            "id": key,
            "name": latest.actor_name or latest.actor_email or "anonymous",
            "email": latest.actor_email,
            "mins": round((now - latest.timestamp).total_seconds() / 60, 1),
            "last_active": latest.timestamp.isoformat(),
            "status": "feedback" if latest.kind is EventKind.FEEDBACK else "serving",
            "area": sample.area,
            "task": sample.task,
            "queries": len(queries),
            "feedback_sent": len(feedback),
            "decisions_received": sum(e.result_count for e in queries),
            "served": _served_decisions(store, sample.decision_ids),
        })

    agents.sort(key=lambda a: a["mins"])  # most recent first
    return {
        "window_mins": window_mins,
        "total_agents": len(agents),
        "total_served": sum(a["decisions_received"] for a in agents),
        "total_feedback": sum(a["feedback_sent"] for a in agents),
        "agents": agents,
    }


def _timedelta_mins(mins: int):
    from datetime import timedelta

    return timedelta(minutes=mins)


def _served_decisions(store: DecisionStore, decision_ids: list[str]) -> list[dict]:
    out = []
    for pid in decision_ids:
        decision = store.get(pid)
        if decision is not None:
            out.append({"id": decision.id, "pattern": decision.pattern,
                        "scope": decision.scope, "confidence": decision.confidence.value})
    return out


def origin_breakdown(store: DecisionStore, *, repo: str | None = None) -> dict:
    """Curation outcome per decision origin (ingest vs feedback vs agent-submitted).

    ``accept_rate`` = canonical / (canonical + rejected) — the share of *decided*
    decisions that were accepted — or None when nothing from that origin is curated
    yet. This is the "are feedback-born decisions better than ingest-born?" view.
    """
    repo_filter = repo or None
    origins = []
    for o in Origin:
        canonical = store.count(repo=repo_filter, status=Status.CANONICAL, origin=o)
        rejected = store.count(repo=repo_filter, status=Status.REJECTED, origin=o)
        candidate = store.count(repo=repo_filter, status=Status.CANDIDATE, origin=o)
        total = candidate + canonical + rejected
        if total == 0:
            continue
        decided = canonical + rejected
        origins.append({
            "origin": o.value,
            "candidate": candidate,
            "canonical": canonical,
            "rejected": rejected,
            "total": total,
            "accept_rate": round(canonical / decided, 3) if decided else None,
        })
    return {"origins": origins}


def feedback_analytics(
    event_store: EventStore, store: DecisionStore, *, repo: str | None = None
) -> dict:
    """Advisory helpful/noise tallies from feedback events.

    Per-decision counts (noisiest first, to guide review) and a per-origin rollup with
    a helpful-rate. Read-only: this never changes a decision's status or confidence.
    """
    repo_filter = repo or None
    feedback = [
        e for e in event_store.list_events(repo=repo_filter)
        if e.kind is EventKind.FEEDBACK
    ]
    helpful: Counter = Counter()
    noise: Counter = Counter()
    for e in feedback:
        helpful.update(e.helpful_decision_ids)
        noise.update(e.unhelpful_decision_ids)

    decisions, by_origin = [], {}
    for pid in set(helpful) | set(noise):
        decision = store.get(pid)
        origin = decision.origin.value if decision is not None else "unknown"
        h, n = helpful[pid], noise[pid]
        decisions.append({
            "id": pid,
            "pattern": decision.pattern if decision is not None else "(deleted)",
            "origin": origin,
            "helpful": h,
            "noise": n,
        })
        agg = by_origin.setdefault(origin, [0, 0])
        agg[0] += h
        agg[1] += n

    decisions.sort(key=lambda p: (p["helpful"] - p["noise"], p["id"]))  # noisiest first
    by_origin_out = [
        {
            "origin": origin,
            "helpful": h,
            "noise": n,
            "helpful_rate": round(h / (h + n), 3) if (h + n) else None,
        }
        for origin, (h, n) in by_origin.items()
    ]
    return {"decisions": decisions, "by_origin": by_origin_out}


# A decision needs at least this many ratings before we'll flag it as "misleading":
# one bad rating is noise, a pattern of them is signal.
_REVIEW_MIN_RATINGS = 2
_LEADERBOARD_TOP_N = 10


def leaderboard(
    event_store: EventStore, store: DecisionStore, *, repo: str | None = None,
    top_n: int = _LEADERBOARD_TOP_N,
) -> dict:
    """Canonical decisions ranked by agent-rated helpfulness.

    Two lists over the repo's *canonical* decisions (only those are served, so only
    those can be reordered): ``most_helpful`` (highest scores, carrying their weight)
    and ``misleading`` (lowest scores among decisions with enough ratings to trust — the
    human review queue). Read-only: this surfaces what to curate and never mutates a
    decision. ``effect`` is the serve-ranking direction this score induces (up/down/flat).
    """
    repo_filter = repo or None
    scores = helpfulness_scores(event_store.list_events(repo=repo_filter))
    canonical = {p.id: p for p in store.list(repo=repo_filter, status=Status.CANONICAL)}

    rated = []
    for pid, s in scores.items():
        decision = canonical.get(pid)
        if decision is None:  # rate only what is currently canonical / served
            continue
        rated.append({
            "id": pid,
            "pattern": decision.pattern,
            "scope": decision.scope,
            "score": round(s.score, 2),
            "n_ratings": s.n_ratings,
            "effect": "up" if s.centered > 0 else "down" if s.centered < 0 else "flat",
        })

    most_helpful = sorted(rated, key=lambda r: (-r["score"], r["id"]))[:top_n]
    misleading = sorted(
        (r for r in rated
         if r["n_ratings"] >= _REVIEW_MIN_RATINGS and r["score"] < NEUTRAL),
        key=lambda r: (r["score"], r["id"]),
    )[:top_n]
    return {
        "neutral": NEUTRAL,
        "rated_total": len(rated),
        "review_count": len(misleading),
        "most_helpful": most_helpful,
        "misleading": misleading,
    }


def feedback_events(
    event_store: EventStore,
    store: DecisionStore,
    *,
    repo: str | None = None,
    status: str = "all",
    recent: int = 100,
) -> dict:
    """The raw feedback stream — what agents actually told us, newest-first.

    Each event carries the free-text gap ("what was missing"), the decisions flagged
    helpful/unhelpful (resolved for display), whether it's been refined yet, and the
    candidates it produced once handled. ``status`` filters to "handled"/"unhandled"
    ("all" by default). For a handled event, each produced candidate carries its
    current curation status plus usefulness signals tallied from later usage — how
    often it was served by a query and rated helpful/unhelpful — so curators can see
    whether a refined decision is actually earning its place. This is the read view
    behind the Feedback page.
    """
    repo_filter = repo or None
    all_events = list(event_store.list_events(repo=repo_filter))

    # Tally usefulness per decision id from later usage: served = appearances in QUERY
    # results; helpful/unhelpful = ratings on subsequent feedback events.
    served, helpful_n, unhelpful_n = Counter(), Counter(), Counter()
    for e in all_events:
        if e.kind is EventKind.QUERY:
            served.update(e.decision_ids)
        elif e.kind is EventKind.FEEDBACK:
            helpful_n.update(e.helpful_decision_ids)
            unhelpful_n.update(e.unhelpful_decision_ids)

    feedback = [e for e in all_events if e.kind is EventKind.FEEDBACK]
    if status == "handled":
        feedback = [e for e in feedback if e.handled]
    elif status == "unhandled":
        feedback = [e for e in feedback if not e.handled]
    feedback = feedback[:recent]

    def resolve(ids: list[str], *, with_stats: bool = False) -> list[dict]:
        out = []
        for pid in ids:
            decision = store.get(pid)
            entry = {
                "id": pid,
                "pattern": decision.pattern if decision is not None else "(deleted)",
                "scope": decision.scope if decision is not None else "",
                "origin": decision.origin.value if decision is not None else "unknown",
            }
            if with_stats:
                entry["rationale"] = decision.rationale if decision is not None else ""
                entry["status"] = decision.status.value if decision is not None else "deleted"
                entry["served"] = served.get(pid, 0)
                entry["helpful"] = helpful_n.get(pid, 0)
                entry["unhelpful"] = unhelpful_n.get(pid, 0)
            out.append(entry)
        return out

    events = [
        {
            "id": e.id,
            "timestamp": e.timestamp.isoformat(),
            "area": e.area,
            "missing": e.missing,
            "handled": e.handled,
            "version": e.version,
            "actor_id": e.actor_id,
            "actor_email": e.actor_email,
            "actor_name": e.actor_name,
            "ratings": e.ratings,
            "query_ref": e.query_ref,
            "helpful": resolve(e.helpful_decision_ids),
            "unhelpful": resolve(e.unhelpful_decision_ids),
            "produced": resolve(e.decision_ids, with_stats=True) if e.handled else [],
        }
        for e in feedback
    ]
    return {"events": events}


def refine_one(store: DecisionStore, event_store, refiner_factory, event_id: str) -> dict:
    """Run the LLM refiner on a single feedback event (the UI "Refine" button).

    ``refiner_factory`` lazily builds the refiner (so the API key/provider is only
    touched on demand). If none is configured — e.g. no API key — return a clean
    ``ok: False`` rather than a 500, and surface provider/parse errors the same way.
    Idempotent: an already-handled event reports ``events_processed: 0``.
    """
    if event_store is None:
        return {"ok": False, "error": "No event store configured."}
    if refiner_factory is None:
        return {
            "ok": False,
            "error": "Refinement unavailable — no LLM provider configured. "
                     "Set ANTHROPIC_API_KEY and restart `metatron ui`.",
        }
    from metatron.pipeline import refine_feedback_event

    try:
        refiner = refiner_factory()
        result = refine_feedback_event(store, event_store, refiner, event_id)
    except Exception as exc:  # provider/network/parse errors -> message, not a crash
        return {"ok": False, "error": str(exc)}
    return {
        "ok": True,
        "events_processed": result.events_processed,
        "decisions_created": result.decisions_created,
    }


def _set_status(store: DecisionStore, decision_id: str, status: Status) -> dict:
    try:
        decision = store.set_status(decision_id, status)
    except KeyError:
        return {"ok": False, "error": f"No decision with id {decision_id!r} (not found)."}
    return {"ok": True, "id": decision.id, "status": decision.status.value}
