"""The CLI routes through the per-repo catalog: resolution, single-file mode, --db."""

import io

from metatron.cli import _resolve_repo, main
from metatron.config import Settings
from metatron.models import Origin, Prior, Status
from metatron.storage.catalog import Catalog, CatalogPriorStore


def _prior(repo, pattern="p", status=Status.CANONICAL):
    return Prior(repo=repo, pattern=pattern, scope="a", rationale="r",
                 origin=Origin.BOOTSTRAP, status=status)


def test_resolve_repo_uses_catalog_listing(tmp_path):
    store = CatalogPriorStore(Catalog(str(tmp_path)))
    store.add(_prior("only/repo"))
    # sole repo in the catalog -> resolved with no flags
    assert _resolve_repo(None, store, Settings()) == "only/repo"


def test_db_flag_single_file_mode_resolves_lone_repo(tmp_path, monkeypatch):
    # Build a single-repo catalog dir, locate its file, then drive `main()` with
    # --db pointing at that file: the recipient's path, no --repo needed.
    cat = Catalog(str(tmp_path / "data"))
    CatalogPriorStore(cat).add(_prior("acme/app", "ship me", status=Status.CANDIDATE))
    file_path = cat.path_for("acme/app")
    cat.close()

    # Keep config defaults out of the way (no stray METATRON_DB/REPO in the env).
    monkeypatch.delenv("METATRON_DB", raising=False)
    monkeypatch.delenv("METATRON_REPO", raising=False)

    out = io.StringIO()
    rc = main(["--db", str(file_path), "candidates", "list"], out=out)
    assert rc == 0
    assert "ship me" in out.getvalue()
