import json
from pathlib import Path
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
    assert len(list((root / "metatron" / "candidate").glob("*.md"))) == 1
    assert len(list((root / "metatron" / "decisions").glob("*.md"))) == 1

def test_export_writes_sync_state_hashes(tmp_path):
    store = _store(tmp_path)
    d = store.add(Decision(repo="r", pattern="p", scope="a", rationale="x",
                           origin=Origin.HUMAN, status=Status.CANDIDATE))
    root = tmp_path / "mirror"
    export_bundle(store, repo="r", root=root, events=[])
    state = json.loads((root / "metatron" / ".sync-state.json").read_text())
    assert d.id in state

def test_export_is_idempotent(tmp_path):
    store = _store(tmp_path)
    store.add(Decision(repo="r", pattern="p", scope="a", rationale="x",
                       origin=Origin.HUMAN, status=Status.CANDIDATE))
    root = tmp_path / "mirror"
    export_bundle(store, repo="r", root=root, events=[])
    first = {str(p): p.read_text() for p in (root / "metatron").rglob("*.md")}
    export_bundle(store, repo="r", root=root, events=[])
    second = {str(p): p.read_text() for p in (root / "metatron").rglob("*.md")}
    assert first == second
