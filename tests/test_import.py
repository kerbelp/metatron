"""Merging an employee's per-repo DB into a curator's catalog (with attribution)."""

import io

from metatron.cli import main
from metatron.events import Event, EventKind
from metatron.models import Origin, Prior, Status
from metatron.storage.catalog import Catalog, CatalogEventStore, CatalogPriorStore
from metatron.storage.transfer import import_catalog


def _seed(catalog, repo, pattern, *, actor):
    CatalogPriorStore(catalog).add(Prior(repo=repo, pattern=pattern, scope="a",
                                         rationale="r", origin=Origin.BOOTSTRAP,
                                         status=Status.CANONICAL))
    CatalogEventStore(catalog).record(Event(repo=repo, kind=EventKind.FEEDBACK,
                                            missing=f"gap from {actor}", actor_name=actor))


def test_import_merges_repo_rows_and_preserves_attribution(tmp_path):
    src = Catalog(str(tmp_path / "src"))
    _seed(src, "acme/app", "from-employee-A", actor="Alice")
    dst = Catalog(str(tmp_path / "dst"))
    _seed(dst, "acme/app", "from-curator", actor="Curator")

    counts = import_catalog(src, dst)
    assert counts["acme/app"]["priors"] == 1 and counts["acme/app"]["events"] == 1

    patterns = {p.pattern for p in CatalogPriorStore(dst).list(repo="acme/app")}
    assert patterns == {"from-employee-A", "from-curator"}
    # attribution survived the merge
    gaps = {e.actor_name for e in CatalogEventStore(dst).list_events(repo="acme/app")}
    assert gaps == {"Alice", "Curator"}


def test_import_is_idempotent(tmp_path):
    src = Catalog(str(tmp_path / "src"))
    _seed(src, "acme/app", "x", actor="Alice")
    dst = Catalog(str(tmp_path / "dst"))

    assert import_catalog(src, dst)["acme/app"]["priors"] == 1
    # second import copies nothing new
    again = import_catalog(src, dst)
    assert again["acme/app"]["priors"] == 0 and again["acme/app"]["events"] == 0
    assert len(CatalogPriorStore(dst).list(repo="acme/app")) == 1


def test_import_cli_merges_a_handed_off_file(tmp_path, monkeypatch):
    # Employee exports a single-repo file; curator imports it into their catalog.
    employee = Catalog(str(tmp_path / "employee"))
    _seed(employee, "acme/app", "shipped-prior", actor="Alice")
    handoff = employee.path_for("acme/app")

    monkeypatch.setenv("METATRON_DB", str(tmp_path / "curator"))
    out = io.StringIO()
    rc = main(["import", str(handoff)], out=out)
    assert rc == 0 and "acme/app" in out.getvalue()

    curator = Catalog(str(tmp_path / "curator"))
    assert [p.pattern for p in CatalogPriorStore(curator).list(repo="acme/app")] == ["shipped-prior"]
