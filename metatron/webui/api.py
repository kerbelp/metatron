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
    page: int = 1,
    page_size: int = 20,
) -> dict:
    page = max(1, page)
    page_size = max(1, page_size)
    status_enum = Status(status) if status else None
    triage_enum = TriageVerdict(triage) if triage else None
    scope_filter = scope or None
    repo_filter = repo or None

    total = store.count(
        repo=repo_filter, status=status_enum, scope=scope_filter, triage=triage_enum
    )
    items = store.list(
        repo=repo_filter,
        status=status_enum,
        scope=scope_filter,
        triage=triage_enum,
        limit=page_size,
        offset=(page - 1) * page_size,
    )
    return {
        "items": [p.model_dump(mode="json") for p in items],
        "page": page,
        "page_size": page_size,
        "total": total,
        "pages": (total + page_size - 1) // page_size,
        "repo": repo,
        "status": status,
        "scope": scope,
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


def _set_status(store: PriorStore, prior_id: str, status: Status) -> dict:
    try:
        prior = store.set_status(prior_id, status)
    except KeyError:
        return {"ok": False, "error": f"No prior with id {prior_id!r} (not found)."}
    return {"ok": True, "id": prior.id, "status": prior.status.value}
