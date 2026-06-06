"""Catalog-backed stores: route by repo, fan out across files when repo is None."""

from metatron.events import Event, EventKind
from metatron.models import Origin, Decision, Status
from metatron.storage.catalog import (
    Catalog,
    CatalogEventStore,
    CatalogIngestRunStore,
    CatalogDecisionStore,
)
from metatron.models import IngestRun


def _decision(repo, pattern):
    return Decision(repo=repo, pattern=pattern, scope="app", rationale="r",
                 origin=Origin.BOOTSTRAP, status=Status.CANONICAL)


def test_add_routes_to_repo_file_and_list_repos_aggregates(tmp_path):
    store = CatalogDecisionStore(Catalog(str(tmp_path)))
    store.add(_decision("repoA", "alpha"))
    store.add(_decision("repoB", "beta"))
    assert store.list_repos() == ["repoA", "repoB"]
    assert [p.pattern for p in store.list(repo="repoA")] == ["alpha"]
    assert {p.pattern for p in store.list()} == {"alpha", "beta"}  # repo=None fans out
    assert store.count() == 2
    assert store.count(repo="repoB") == 1


def test_get_and_set_status_find_owning_file(tmp_path):
    store = CatalogDecisionStore(Catalog(str(tmp_path)))
    p = store.add(_decision("repoA", "alpha"))
    assert store.get(p.id).pattern == "alpha"  # id-only search
    store.set_status(p.id, Status.REJECTED)
    assert store.get(p.id).status is Status.REJECTED


def test_event_store_routes_and_resolves_by_id(tmp_path):
    es = CatalogEventStore(Catalog(str(tmp_path)))
    e = es.record(Event(repo="repoA", kind=EventKind.QUERY, decision_ids=["x"]))
    es.record(Event(repo="repoB", kind=EventKind.QUERY, decision_ids=["y"]))
    assert es.get(e.id).repo == "repoA"
    assert es.count_events() == 2
    assert es.count_events(repo="repoA") == 1
    assert [ev.repo for ev in es.list_events(repo="repoB")] == ["repoB"]


def test_ingest_run_store_routes_and_aggregates(tmp_path):
    rs = CatalogIngestRunStore(Catalog(str(tmp_path)))

    def _run(repo):
        return IngestRun(repo=repo, model="m", files_parsed=1, commits_read=1,
                         scopes=1, decisions_created=1, input_tokens=1, output_tokens=1)

    rs.record(_run("repoA"))
    rs.record(_run("repoB"))
    assert {r.repo for r in rs.list_for_repo(None)} == {"repoA", "repoB"}
    assert [r.repo for r in rs.list_for_repo("repoA")] == ["repoA"]
