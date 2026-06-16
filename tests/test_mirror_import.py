import shutil
import json
from metatron.models import Decision, Origin, Status, Confidence
from metatron.storage.sqlite import SQLiteDecisionStore
from metatron.mirror.export import export_bundle
from metatron.mirror.sync_import import import_bundle


def _store(tmp_path):
    return SQLiteDecisionStore(str(tmp_path / "d.db"))


def test_moving_file_to_decisions_promotes_to_canonical(tmp_path):
    store = _store(tmp_path)
    d = store.add(Decision(repo="r", pattern="p", scope="a", rationale="x",
                           origin=Origin.AGENT_SUBMITTED, status=Status.CANDIDATE))
    root = tmp_path / "mirror"
    export_bundle(store, repo="r", root=root, events=[])
    src = next((root / "metatron" / "candidate").glob("*.md"))
    dst = root / "metatron" / "decisions" / src.name
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    result = import_bundle(store, repo="r", root=root)
    assert store.get(d.id).status == Status.CANONICAL
    assert d.id in result.promoted


def test_editing_keywords_in_file_is_ignored_and_warns(tmp_path):
    store = _store(tmp_path)
    d = store.add(Decision(repo="r", pattern="p", scope="a", rationale="x",
                           origin=Origin.HUMAN, status=Status.CANDIDATE,
                           keywords=["orig"]))
    root = tmp_path / "mirror"
    export_bundle(store, repo="r", root=root, events=[])
    f = next((root / "metatron" / "candidate").glob("*.md"))
    f.write_text(f.read_text().replace("orig", "hacked"))
    res = import_bundle(store, repo="r", root=root)
    assert store.get(d.id).keywords == ["orig"]      # unchanged
    assert any("keyword" in w.lower() or "read-only" in w.lower() for w in res.warnings)


def test_concurrent_db_and_file_edit_is_a_conflict(tmp_path):
    store = _store(tmp_path)
    d = store.add(Decision(repo="r", pattern="orig", scope="a", rationale="x",
                           origin=Origin.HUMAN, status=Status.CANDIDATE))
    root = tmp_path / "mirror"
    export_bundle(store, repo="r", root=root, events=[])     # records baseline fingerprint
    store.update_fields(d.id, pattern="db-changed")          # DB changes a human field
    f = next((root / "metatron" / "candidate").glob("*.md"))
    f.write_text(f.read_text().replace("## Pattern\norig", "## Pattern\nfile-changed"))
    res = import_bundle(store, repo="r", root=root)
    assert d.id in res.conflicts
    assert store.get(d.id).pattern == "db-changed"           # not clobbered


def test_clean_file_edit_applies(tmp_path):
    store = _store(tmp_path)
    d = store.add(Decision(repo="r", pattern="orig", scope="a", rationale="x",
                           origin=Origin.HUMAN, status=Status.CANDIDATE))
    root = tmp_path / "mirror"
    export_bundle(store, repo="r", root=root, events=[])
    f = next((root / "metatron" / "candidate").glob("*.md"))
    f.write_text(f.read_text().replace("## Pattern\norig", "## Pattern\nedited"))
    res = import_bundle(store, repo="r", root=root)
    assert store.get(d.id).pattern == "edited"
    assert d.id in res.updated


def test_stray_non_status_md_does_not_crash_import(tmp_path):
    # Bug 1: a plausible metatron/README.md must be ignored, not abort the import.
    store = _store(tmp_path)
    d = store.add(Decision(repo="r", pattern="orig", scope="a", rationale="x",
                           origin=Origin.HUMAN, status=Status.CANDIDATE))
    root = tmp_path / "mirror"
    export_bundle(store, repo="r", root=root, events=[])
    (root / "metatron" / "README.md").write_text("# Notes\n\narbitrary text\n")
    f = next((root / "metatron" / "candidate").glob("*.md"))
    f.write_text(f.read_text().replace("## Pattern\norig", "## Pattern\nedited"))
    res = import_bundle(store, repo="r", root=root)  # must not raise
    assert store.get(d.id).pattern == "edited"
    assert d.id in res.updated


def test_missing_baseline_with_divergence_is_a_conflict(tmp_path):
    # Bug 2: when the sync baseline is gone, a DB-vs-file divergence must surface
    # as a conflict, not silently let the file clobber the DB.
    store = _store(tmp_path)
    d = store.add(Decision(repo="r", pattern="orig", scope="a", rationale="x",
                           origin=Origin.HUMAN, status=Status.CANDIDATE))
    root = tmp_path / "mirror"
    export_bundle(store, repo="r", root=root, events=[])
    (root / "metatron" / ".sync-state.json").unlink()        # baseline gone
    store.update_fields(d.id, pattern="db-changed")          # DB diverges
    f = next((root / "metatron" / "candidate").glob("*.md"))
    f.write_text(f.read_text().replace("## Pattern\norig", "## Pattern\nfile-changed"))
    res = import_bundle(store, repo="r", root=root)
    assert d.id in res.conflicts
    assert store.get(d.id).pattern == "db-changed"           # not clobbered


def test_new_file_without_id_creates_a_decision(tmp_path):
    store = _store(tmp_path)
    root = tmp_path / "mirror"
    d_dir = root / "metatron" / "decisions"
    d_dir.mkdir(parents=True)
    (d_dir / "hand-authored.md").write_text(
        "---\nscope: web\nconfidence: high\n---\n\n"
        "## Pattern\nAlways gzip API responses.\n\n## Rationale\nBandwidth.\n")
    res = import_bundle(store, repo="r", root=root)
    created = store.list(repo="r", status=Status.CANONICAL)
    assert len(created) == 1
    assert created[0].pattern == "Always gzip API responses."
    assert created[0].rationale == "Bandwidth."
    assert created[0].origin == Origin.HUMAN
    assert created[0].scope == "web"
    assert created[0].confidence == Confidence.HIGH
    assert created[0].id in res.updated


def test_clearing_rationale_field_applies(tmp_path):
    # Bug 3: clearing a human body field is a legitimate edit and must apply.
    store = _store(tmp_path)
    d = store.add(Decision(repo="r", pattern="p", scope="a", rationale="keep-me",
                           origin=Origin.HUMAN, status=Status.CANDIDATE))
    root = tmp_path / "mirror"
    export_bundle(store, repo="r", root=root, events=[])
    f = next((root / "metatron" / "candidate").glob("*.md"))
    f.write_text(f.read_text().replace("## Rationale\nkeep-me", "## Rationale\n"))
    res = import_bundle(store, repo="r", root=root)
    assert store.get(d.id).rationale == ""
    assert d.id in res.updated
