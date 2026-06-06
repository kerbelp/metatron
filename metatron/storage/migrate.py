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
from metatron.storage.transfer import copy_repo_rows


def migrate_legacy_db(legacy_path: str | Path, catalog: Catalog) -> bool:
    """Copy each repo's rows from ``legacy_path`` into its catalog file, then archive.

    Idempotent: returns ``False`` (no-op) once the legacy file is gone/archived. The
    copy goes through the stores (dedupe by id), so it stays schema-safe and re-running
    after an interruption converges until the final archive rename succeeds.
    """
    legacy = Path(legacy_path)
    if not legacy.is_file():
        return False

    priors = SQLitePriorStore(str(legacy))
    events = SQLiteEventStore(str(legacy))
    runs = SQLiteIngestRunStore(str(legacy))
    try:
        for repo in priors.list_repos():
            copy_repo_rows(priors, events, runs, catalog.open(repo), repo)
    finally:
        priors.close()
        events.close()
        runs.close()

    archive = legacy.with_name(f"{legacy.name}.migrated-{date.today().isoformat()}")
    legacy.rename(archive)
    return True
