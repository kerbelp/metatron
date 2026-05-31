"""Web API logic: pure functions from a store to JSON-able dicts.

Kept independent of the HTTP layer so it can be tested directly. The HTTP handler
in :mod:`metatron.webui.server` is a thin adapter over these.
"""

from __future__ import annotations

from metatron.models import Status
from metatron.storage.base import EventStore, PriorStore
from metatron.webui.observability import usage_summary


def list_priors(
    store: PriorStore,
    *,
    repo: str | None = None,
    status: str | None = None,
    scope: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    page = max(1, page)
    page_size = max(1, page_size)
    status_enum = Status(status) if status else None
    scope_filter = scope or None
    repo_filter = repo or None

    total = store.count(repo=repo_filter, status=status_enum, scope=scope_filter)
    items = store.list(
        repo=repo_filter,
        status=status_enum,
        scope=scope_filter,
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


def approve(store: PriorStore, prior_id: str) -> dict:
    return _set_status(store, prior_id, Status.CANONICAL)


def reject(store: PriorStore, prior_id: str) -> dict:
    return _set_status(store, prior_id, Status.REJECTED)


def stats(store: PriorStore, *, repo: str | None = None) -> dict:
    repo_filter = repo or None
    counts = {s.value: store.count(repo=repo_filter, status=s) for s in Status}
    counts["total"] = store.count(repo=repo_filter)
    return counts


def usage(event_store: EventStore, *, repo: str | None = None, recent: int = 25) -> dict:
    repo_filter = repo or None
    summary = usage_summary(event_store.list_events(repo=repo_filter))
    summary["recent"] = [
        e.model_dump(mode="json")
        for e in event_store.list_events(repo=repo_filter, limit=recent)
    ]
    return summary


def _set_status(store: PriorStore, prior_id: str, status: Status) -> dict:
    try:
        prior = store.set_status(prior_id, status)
    except KeyError:
        return {"ok": False, "error": f"No prior with id {prior_id!r} (not found)."}
    return {"ok": True, "id": prior.id, "status": prior.status.value}
