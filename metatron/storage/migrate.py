"""One-time split of a legacy single ``metatron.db`` into per-repo catalog files."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from metatron.storage.catalog import Catalog
from metatron.storage.sqlite import (
    SQLiteEventStore,
    SQLiteIngestRunStore,
    SQLitePriorStore,
)


def migrate_legacy_db(legacy_path: str | Path, catalog: Catalog) -> bool:
    """Copy each repo's rows from ``legacy_path`` into its catalog file, then archive.

    Idempotent: returns ``False`` (no-op) once the legacy file is gone/archived. The
    copy goes through the stores (read filtered by repo, write into the new file), so
    it stays schema-safe. Re-running after an interruption re-copies until the final
    archive rename succeeds.
    """
    legacy = Path(legacy_path)
    if not legacy.is_file():
        return False

    priors = SQLitePriorStore(str(legacy))
    events = SQLiteEventStore(str(legacy))
    runs = SQLiteIngestRunStore(str(legacy))
    try:
        for repo in priors.list_repos():
            dst = catalog.open(repo)
            # Skip rows already present so an interrupted run (rows copied but the
            # archive rename below not yet reached) re-runs cleanly instead of
            # tripping a PRIMARY KEY conflict on the second pass.
            for p in priors.list(repo=repo):
                if dst.priors.get(p.id) is None:
                    dst.priors.add(p)
            for e in events.list_events(repo=repo):
                if dst.events.get(e.id) is None:
                    dst.events.record(e)
            existing_runs = {r.id for r in dst.runs.list_for_repo(repo)}
            for r in runs.list_for_repo(repo):
                if r.id not in existing_runs:
                    dst.runs.record(r)
    finally:
        priors.close()
        events.close()
        runs.close()

    archive = legacy.with_name(f"{legacy.name}.migrated-{date.today().isoformat()}")
    legacy.rename(archive)
    return True
