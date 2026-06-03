"""Web API logic: pure functions from a store to JSON-able dicts.

Kept independent of the HTTP layer so it can be tested directly. The HTTP handler
in :mod:`metatron.webui.server` is a thin adapter over these.
"""

from __future__ import annotations

from collections import Counter

from metatron.events import EventKind
from metatron.models import Origin, Status, TriageVerdict
from metatron.pricing import estimate_cost
from metatron.storage.base import EventStore, PriorStore
from metatron.version import version_string
from metatron.webui.observability import usage_summary


def version() -> dict:
    """The code revision this server is running (shown in the UI footer)."""
    return {"revision": version_string()}


def list_priors(
    store: PriorStore,
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


def repos(store: PriorStore) -> dict:
    return {"repos": store.list_repos()}


def ingest_cost(run_store, *, repo: str | None = None) -> dict:
    runs = []
    for run in run_store.list_for_repo(repo):
        data = run.model_dump(mode="json")
        data["estimated_cost"] = estimate_cost(
            run.model, run.input_tokens, run.output_tokens
        )
        runs.append(data)
    return {"runs": runs}


def approve(store: PriorStore, prior_id: str) -> dict:
    return _set_status(store, prior_id, Status.CANONICAL)


def reject(store: PriorStore, prior_id: str) -> dict:
    return _set_status(store, prior_id, Status.REJECTED)


def approve_recommended(store: PriorStore, *, repo: str | None = None) -> dict:
    """Promote every candidate the judge marked ``approve`` to canonical, at once.

    This is the one-click "Approve recommended" action: a human triggers it after
    reviewing the valuation, so the human-in-the-loop invariant holds — nothing
    self-promotes, the person decides to accept the recommended batch.
    """
    repo_filter = repo or None
    recommended = store.list(
        repo=repo_filter, status=Status.CANDIDATE, triage=TriageVerdict.APPROVE
    )
    for prior in recommended:
        store.set_status(prior.id, Status.CANONICAL)
    return {"ok": True, "approved": len(recommended)}


def stats(store: PriorStore, *, repo: str | None = None) -> dict:
    repo_filter = repo or None
    counts = {s.value: store.count(repo=repo_filter, status=s) for s in Status}
    counts["total"] = store.count(repo=repo_filter)
    return counts


def usage(
    event_store: EventStore,
    store: PriorStore,
    *,
    repo: str | None = None,
    recent: int = 25,
) -> dict:
    repo_filter = repo or None
    events = event_store.list_events(repo=repo_filter)  # newest-first
    summary = usage_summary(events)

    def enrich(event) -> dict:
        data = event.model_dump(mode="json")
        priors = []
        for prior_id in event.prior_ids:
            prior = store.get(prior_id)
            if prior is not None:
                priors.append(
                    {
                        "id": prior.id,
                        "pattern": prior.pattern,
                        "scope": prior.scope,
                        "confidence": prior.confidence.value,
                        "rationale": prior.rationale,
                    }
                )
        data["priors"] = priors
        return data

    summary["recent_queries"] = [
        enrich(e) for e in events if e.kind is EventKind.QUERY
    ][:recent]
    summary["recent_submissions"] = [
        enrich(e) for e in events if e.kind is EventKind.SUBMIT
    ][:recent]
    return summary


def origin_breakdown(store: PriorStore, *, repo: str | None = None) -> dict:
    """Curation outcome per prior origin (ingest vs feedback vs agent-submitted).

    ``accept_rate`` = canonical / (canonical + rejected) — the share of *decided*
    priors that were accepted — or None when nothing from that origin is curated
    yet. This is the "are feedback-born priors better than ingest-born?" view.
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
    event_store: EventStore, store: PriorStore, *, repo: str | None = None
) -> dict:
    """Advisory helpful/noise tallies from feedback events.

    Per-prior counts (noisiest first, to guide review) and a per-origin rollup with
    a helpful-rate. Read-only: this never changes a prior's status or confidence.
    """
    repo_filter = repo or None
    feedback = [
        e for e in event_store.list_events(repo=repo_filter)
        if e.kind is EventKind.FEEDBACK
    ]
    helpful: Counter = Counter()
    noise: Counter = Counter()
    for e in feedback:
        helpful.update(e.helpful_prior_ids)
        noise.update(e.unhelpful_prior_ids)

    priors, by_origin = [], {}
    for pid in set(helpful) | set(noise):
        prior = store.get(pid)
        origin = prior.origin.value if prior is not None else "unknown"
        h, n = helpful[pid], noise[pid]
        priors.append({
            "id": pid,
            "pattern": prior.pattern if prior is not None else "(deleted)",
            "origin": origin,
            "helpful": h,
            "noise": n,
        })
        agg = by_origin.setdefault(origin, [0, 0])
        agg[0] += h
        agg[1] += n

    priors.sort(key=lambda p: (p["helpful"] - p["noise"], p["id"]))  # noisiest first
    by_origin_out = [
        {
            "origin": origin,
            "helpful": h,
            "noise": n,
            "helpful_rate": round(h / (h + n), 3) if (h + n) else None,
        }
        for origin, (h, n) in by_origin.items()
    ]
    return {"priors": priors, "by_origin": by_origin_out}


def feedback_events(
    event_store: EventStore,
    store: PriorStore,
    *,
    repo: str | None = None,
    status: str = "all",
    recent: int = 100,
) -> dict:
    """The raw feedback stream — what agents actually told us, newest-first.

    Each event carries the free-text gap ("what was missing"), the priors flagged
    helpful/unhelpful (resolved for display), whether it's been refined yet, and the
    candidates it produced once handled. ``status`` filters to "handled"/"unhandled"
    ("all" by default). For a handled event, each produced candidate carries its
    current curation status plus usefulness signals tallied from later usage — how
    often it was served by a query and rated helpful/unhelpful — so curators can see
    whether a refined prior is actually earning its place. This is the read view
    behind the Feedback page.
    """
    repo_filter = repo or None
    all_events = list(event_store.list_events(repo=repo_filter))

    # Tally usefulness per prior id from later usage: served = appearances in QUERY
    # results; helpful/unhelpful = ratings on subsequent feedback events.
    served, helpful_n, unhelpful_n = Counter(), Counter(), Counter()
    for e in all_events:
        if e.kind is EventKind.QUERY:
            served.update(e.prior_ids)
        elif e.kind is EventKind.FEEDBACK:
            helpful_n.update(e.helpful_prior_ids)
            unhelpful_n.update(e.unhelpful_prior_ids)

    feedback = [e for e in all_events if e.kind is EventKind.FEEDBACK]
    if status == "handled":
        feedback = [e for e in feedback if e.handled]
    elif status == "unhandled":
        feedback = [e for e in feedback if not e.handled]
    feedback = feedback[:recent]

    def resolve(ids: list[str], *, with_stats: bool = False) -> list[dict]:
        out = []
        for pid in ids:
            prior = store.get(pid)
            entry = {
                "id": pid,
                "pattern": prior.pattern if prior is not None else "(deleted)",
                "scope": prior.scope if prior is not None else "",
                "origin": prior.origin.value if prior is not None else "unknown",
            }
            if with_stats:
                entry["rationale"] = prior.rationale if prior is not None else ""
                entry["status"] = prior.status.value if prior is not None else "deleted"
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
            "query_ref": e.query_ref,
            "helpful": resolve(e.helpful_prior_ids),
            "unhelpful": resolve(e.unhelpful_prior_ids),
            "produced": resolve(e.prior_ids, with_stats=True) if e.handled else [],
        }
        for e in feedback
    ]
    return {"events": events}


def refine_one(store: PriorStore, event_store, refiner_factory, event_id: str) -> dict:
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
        "priors_created": result.priors_created,
    }


def _set_status(store: PriorStore, prior_id: str, status: Status) -> dict:
    try:
        prior = store.set_status(prior_id, status)
    except KeyError:
        return {"ok": False, "error": f"No prior with id {prior_id!r} (not found)."}
    return {"ok": True, "id": prior.id, "status": prior.status.value}
