from metatron.models import Decision, Origin, Status
from metatron.storage.sqlite import SQLiteDecisionStore
from metatron.mirror.okf import export_okf_bundle, validate_okf_bundle

def _store(tmp_path):
    return SQLiteDecisionStore(str(tmp_path / "d.db"))

def test_okf_bundle_validates(tmp_path):
    store = _store(tmp_path)
    store.add(Decision(repo="r", pattern="p", scope="a", rationale="x",
                       origin=Origin.HUMAN, status=Status.CANONICAL))
    root = tmp_path / "okf"
    export_okf_bundle(store, repo="r", root=root, events=[])
    assert validate_okf_bundle(root) == []      # no structural errors

def test_okf_writes_index(tmp_path):
    store = _store(tmp_path)
    store.add(Decision(repo="r", pattern="p", scope="a", rationale="x",
                       origin=Origin.HUMAN, status=Status.CANONICAL))
    root = tmp_path / "okf"
    export_okf_bundle(store, repo="r", root=root, events=[])
    assert (root / "metatron" / "index.md").exists()

def test_validate_flags_concept_missing_type(tmp_path):
    root = tmp_path / "okf"
    cdir = root / "metatron" / "decisions"
    cdir.mkdir(parents=True)
    (cdir / "bad.md").write_text("---\nid: x\n---\n\n## Pattern\nno type here\n")
    errors = validate_okf_bundle(root)
    assert errors and any("type" in e.lower() for e in errors)
