"""One-time split of a legacy single metatron.db into per-repo catalog files."""

from metatron.events import Event, EventKind
from metatron.models import Origin, Prior, Status
from metatron.storage.catalog import Catalog, CatalogPriorStore
from metatron.storage.migrate import migrate_legacy_db
from metatron.storage.sqlite import SQLiteEventStore, SQLitePriorStore


def _seed_legacy(path):
    ps = SQLitePriorStore(str(path))
    es = SQLiteEventStore(str(path))
    for repo in ("repoA", "repoB"):
        ps.add(Prior(repo=repo, pattern=f"p-{repo}", scope="app", rationale="r",
                     origin=Origin.BOOTSTRAP, status=Status.CANONICAL))
        es.record(Event(repo=repo, kind=EventKind.QUERY, prior_ids=["x"]))
    ps.close()
    es.close()


def test_migrate_splits_per_repo_and_archives(tmp_path):
    legacy = tmp_path / "metatron.db"
    _seed_legacy(legacy)
    cat = Catalog(str(tmp_path / "data"))

    assert migrate_legacy_db(legacy, cat) is True

    store = CatalogPriorStore(cat)
    assert store.list_repos() == ["repoA", "repoB"]
    assert [p.pattern for p in store.list(repo="repoA")] == ["p-repoA"]
    assert not legacy.exists()
    assert list(tmp_path.glob("metatron.db.migrated-*"))  # archived


def test_migrate_is_idempotent(tmp_path):
    legacy = tmp_path / "metatron.db"
    _seed_legacy(legacy)
    cat = Catalog(str(tmp_path / "data"))
    assert migrate_legacy_db(legacy, cat) is True
    assert migrate_legacy_db(legacy, cat) is False  # nothing left to do


def test_migrate_no_legacy_file_is_noop(tmp_path):
    cat = Catalog(str(tmp_path / "data"))
    assert migrate_legacy_db(tmp_path / "metatron.db", cat) is False
