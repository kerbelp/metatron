"""`metatron export <repo>` produces a standalone, single-file-openable hand-off DB."""

import io

from metatron.cli import _cmd_export, main
from metatron.models import Origin, Prior, Status
from metatron.storage.catalog import Catalog, CatalogPriorStore


def _prior(repo, pattern):
    return Prior(repo=repo, pattern=pattern, scope="a", rationale="r",
                 origin=Origin.BOOTSTRAP, status=Status.CANONICAL)


def test_export_copies_repo_file_and_is_openable_single_file(tmp_path):
    cat = Catalog(str(tmp_path / "data"))
    CatalogPriorStore(cat).add(_prior("acme/app", "ship me"))
    out = tmp_path / "app.db"

    rc = _cmd_export(cat, "acme/app", str(out), io.StringIO())
    assert rc == 0 and out.exists()

    # Opens in single-file mode and serves the same prior — the recipient's path.
    recip = CatalogPriorStore(Catalog(str(out)))
    assert recip.list_repos() == ["acme/app"]
    assert [p.pattern for p in recip.list(repo="acme/app")] == ["ship me"]


def test_export_unknown_repo_reports_and_returns_2(tmp_path):
    cat = Catalog(str(tmp_path / "data"))
    stream = io.StringIO()
    rc = _cmd_export(cat, "nope/missing", None, stream)
    assert rc == 2 and "No data" in stream.getvalue()


def test_export_via_main_resolves_sole_repo(tmp_path, monkeypatch):
    monkeypatch.setenv("METATRON_DB", str(tmp_path / "data"))
    CatalogPriorStore(Catalog(str(tmp_path / "data"))).add(_prior("solo/repo", "p"))
    out = tmp_path / "solo.db"

    rc = main(["export", "--out", str(out)], out=io.StringIO())
    assert rc == 0 and out.exists()
