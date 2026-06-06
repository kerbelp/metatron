"""Copying repo rows between Metatron stores: the primitive behind migrate + import.

Both the one-time legacy split (:mod:`metatron.storage.migrate`) and the curator's
``metatron import`` move a repo's priors/events/ingest-runs into a catalog file,
skipping rows already present (dedupe by id). That dedupe is what makes both
operations idempotent and crash-safe, so it lives here once.
"""

from __future__ import annotations

from metatron.storage.catalog import Catalog, RepoStores
from metatron.storage.sqlite import (
    SQLiteEventStore,
    SQLiteIngestRunStore,
    SQLitePriorStore,
)


def copy_repo_rows(
    src_priors: SQLitePriorStore,
    src_events: SQLiteEventStore,
    src_runs: SQLiteIngestRunStore,
    dst: RepoStores,
    repo: str,
) -> dict[str, int]:
    """Copy one repo's rows from the source stores into ``dst``, skipping existing ids.

    Returns the count of rows actually inserted per kind. Idempotent: re-running
    inserts only rows not already in ``dst`` (so an interrupted run converges and a
    repeat import is a no-op).
    """
    counts = {"priors": 0, "events": 0, "runs": 0}
    for p in src_priors.list(repo=repo):
        if dst.priors.get(p.id) is None:
            dst.priors.add(p)
            counts["priors"] += 1
    for e in src_events.list_events(repo=repo):
        if dst.events.get(e.id) is None:
            dst.events.record(e)
            counts["events"] += 1
    existing_runs = {r.id for r in dst.runs.list_for_repo(repo)}
    for r in src_runs.list_for_repo(repo):
        if r.id not in existing_runs:
            dst.runs.record(r)
            counts["runs"] += 1
    return counts


def import_catalog(src: Catalog, dst: Catalog) -> dict[str, dict[str, int]]:
    """Merge every repo in ``src`` into ``dst`` (dedupe by id). Returns per-repo counts.

    ``src`` may be a single handed-off ``.db`` (single-file mode) or another catalog
    directory. Attribution on the events travels with them, so a curator sees who
    contributed what after the merge.
    """
    result: dict[str, dict[str, int]] = {}
    for repo in src.list_repos():
        s = src.open(repo)
        result[repo] = copy_repo_rows(s.priors, s.events, s.runs, dst.open(repo), repo)
    return result
