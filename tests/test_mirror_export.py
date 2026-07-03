import json
from metatron.models import Decision, Origin, Status
from metatron.storage.sqlite import SQLiteDecisionStore
from metatron.mirror.export import export_bundle

def _store(tmp_path):
    return SQLiteDecisionStore(str(tmp_path / "d.db"))

def test_export_writes_one_file_per_decision_into_status_dirs(tmp_path):
    store = _store(tmp_path)
    store.add(Decision(repo="r", pattern="cand pat", scope="a", rationale="x",
                       origin=Origin.AGENT_SUBMITTED, status=Status.CANDIDATE))
    store.add(Decision(repo="r", pattern="canon pat", scope="b", rationale="y",
                       origin=Origin.HUMAN, status=Status.CANONICAL))
    root = tmp_path / "mirror"
    export_bundle(store, repo="r", root=root, events=[])
    assert len(list((root / "context" / "candidate").glob("*.md"))) == 1
    assert len(list((root / "context" / "decisions").glob("*.md"))) == 1

def test_export_writes_sync_state_hashes(tmp_path):
    store = _store(tmp_path)
    d = store.add(Decision(repo="r", pattern="p", scope="a", rationale="x",
                           origin=Origin.HUMAN, status=Status.CANDIDATE))
    root = tmp_path / "mirror"
    export_bundle(store, repo="r", root=root, events=[])
    state = json.loads((root / "context" / ".sync-state.json").read_text())
    assert d.id in state

def test_export_is_idempotent(tmp_path):
    store = _store(tmp_path)
    store.add(Decision(repo="r", pattern="p", scope="a", rationale="x",
                       origin=Origin.HUMAN, status=Status.CANDIDATE))
    root = tmp_path / "mirror"
    export_bundle(store, repo="r", root=root, events=[])
    first = {str(p): p.read_text() for p in (root / "context").rglob("*.md")}
    export_bundle(store, repo="r", root=root, events=[])
    second = {str(p): p.read_text() for p in (root / "context").rglob("*.md")}
    assert first == second


def test_export_prunes_file_for_rejected_decision(tmp_path):
    # I2: export must mirror the exported set — a decision that leaves the
    # exported set (here, rejected) must have its stale file pruned.
    store = _store(tmp_path)
    keep = store.add(Decision(repo="r", pattern="keep", scope="a", rationale="x",
                              origin=Origin.HUMAN, status=Status.CANDIDATE))
    drop = store.add(Decision(repo="r", pattern="drop", scope="b", rationale="y",
                              origin=Origin.HUMAN, status=Status.CANDIDATE))
    root = tmp_path / "mirror"
    export_bundle(store, repo="r", root=root, events=[])
    cand = root / "context" / "candidate"
    assert len(list(cand.glob("*.md"))) == 2
    store.set_status(drop.id, Status.REJECTED)
    export_bundle(store, repo="r", root=root, events=[])
    files = list(cand.glob("*.md"))
    assert len(files) == 1
    assert keep.pattern in files[0].read_text()


def test_export_promotion_leaves_single_file_in_decisions(tmp_path):
    # I2: flipping CANDIDATE -> CANONICAL must move the file, not duplicate it.
    store = _store(tmp_path)
    d = store.add(Decision(repo="r", pattern="p", scope="a", rationale="x",
                           origin=Origin.HUMAN, status=Status.CANDIDATE))
    root = tmp_path / "mirror"
    export_bundle(store, repo="r", root=root, events=[])
    assert len(list((root / "context" / "candidate").glob("*.md"))) == 1
    store.set_status(d.id, Status.CANONICAL)
    export_bundle(store, repo="r", root=root, events=[])
    assert len(list((root / "context" / "candidate").glob("*.md"))) == 0
    assert len(list((root / "context" / "decisions").glob("*.md"))) == 1


def test_export_does_not_prune_index_or_readme(tmp_path):
    # I2: pruning is confined to candidate/ and decisions/ *.md decision files;
    # index.md and a hand-placed README must survive.
    store = _store(tmp_path)
    store.add(Decision(repo="r", pattern="p", scope="a", rationale="x",
                       origin=Origin.HUMAN, status=Status.CANDIDATE))
    root = tmp_path / "mirror"
    export_bundle(store, repo="r", root=root, events=[])
    mirror = root / "context"
    (mirror / "index.md").write_text("# index\n")
    (mirror / "README.md").write_text("# readme\n")
    export_bundle(store, repo="r", root=root, events=[])
    assert (mirror / "index.md").exists()
    assert (mirror / "README.md").exists()
    assert (mirror / ".sync-state.json").exists()
