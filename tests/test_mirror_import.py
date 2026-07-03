import shutil
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
    src = next((root / "context" / "candidate").glob("*.md"))
    dst = root / "context" / "decisions" / src.name
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
    f = next((root / "context" / "candidate").glob("*.md"))
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
    f = next((root / "context" / "candidate").glob("*.md"))
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
    f = next((root / "context" / "candidate").glob("*.md"))
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
    (root / "context" / "README.md").write_text("# Notes\n\narbitrary text\n")
    f = next((root / "context" / "candidate").glob("*.md"))
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
    (root / "context" / ".sync-state.json").unlink()        # baseline gone
    store.update_fields(d.id, pattern="db-changed")          # DB diverges
    f = next((root / "context" / "candidate").glob("*.md"))
    f.write_text(f.read_text().replace("## Pattern\norig", "## Pattern\nfile-changed"))
    res = import_bundle(store, repo="r", root=root)
    assert d.id in res.conflicts
    assert store.get(d.id).pattern == "db-changed"           # not clobbered


def test_new_file_without_id_creates_a_decision(tmp_path):
    store = _store(tmp_path)
    root = tmp_path / "mirror"
    d_dir = root / "context" / "decisions"
    d_dir.mkdir(parents=True)
    (d_dir / "hand-authored.md").write_text(
        "---\ntype: Metatron Decision\nscope: web\nconfidence: high\n---\n\n"
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
    f = next((root / "context" / "candidate").glob("*.md"))
    f.write_text(f.read_text().replace("## Rationale\nkeep-me", "## Rationale\n"))
    res = import_bundle(store, repo="r", root=root)
    assert store.get(d.id).rationale == ""
    assert d.id in res.updated


def test_import_confined_to_target_repo(tmp_path):
    # A bundle file whose id belongs to repo A must not be applied while importing
    # under repo B: a shared store's get() finds it cross-repo, but import must skip.
    store = _store(tmp_path)
    a = store.add(Decision(repo="A", pattern="p", scope="a", rationale="x",
                           origin=Origin.HUMAN, status=Status.CANDIDATE))
    root = tmp_path / "mirror"
    export_bundle(store, repo="A", root=root, events=[])
    # Move A's exported candidate file into decisions/ (would normally promote).
    src = next((root / "context" / "candidate").glob("*.md"))
    dst = root / "context" / "decisions" / src.name
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    res = import_bundle(store, repo="B", root=root)
    assert store.get(a.id).status == Status.CANDIDATE  # UNCHANGED
    assert a.id not in res.promoted
    assert a.id not in res.updated
    assert any(a.id in w and "different repo" in w for w in res.warnings)


def test_create_honors_source_refs(tmp_path):
    # A hand-authored (no-id) file's source_refs must be honored at creation.
    store = _store(tmp_path)
    root = tmp_path / "mirror"
    d_dir = root / "context" / "decisions"
    d_dir.mkdir(parents=True)
    (d_dir / "hand-authored.md").write_text(
        '---\ntype: Metatron Decision\nscope: web\nconfidence: high\nsource_refs: ["src/x.py:10"]\n---\n\n'
        "## Pattern\nP.\n\n## Rationale\nR.\n")
    import_bundle(store, repo="r", root=root)
    created = store.list(repo="r", status=Status.CANONICAL)
    assert len(created) == 1
    refs = created[0].source_refs
    assert len(refs) == 1
    assert refs[0].ref == "src/x.py:10"


def test_unchanged_bundle_roundtrip_produces_no_warnings(tmp_path):
    # M2: exporting then importing an unedited bundle must not warn.
    store = _store(tmp_path)
    store.add(Decision(repo="r", pattern="p", scope="a", rationale="x",
                       origin=Origin.HUMAN, status=Status.CANDIDATE))
    root = tmp_path / "mirror"
    export_bundle(store, repo="r", root=root, events=[])
    res = import_bundle(store, repo="r", root=root)
    assert res.warnings == []


def test_unedited_datetime_timestamp_does_not_warn(tmp_path):
    # M2: yaml.safe_load turns an unquoted ISO timestamp into a datetime whose
    # str() uses a space, not 'T'. An UNEDITED timestamp in that form must not
    # produce a spurious read-only warning.
    store = _store(tmp_path)
    d = store.add(Decision(repo="r", pattern="p", scope="a", rationale="x",
                           origin=Origin.HUMAN, status=Status.CANDIDATE))
    root = tmp_path / "mirror"
    export_bundle(store, repo="r", root=root, events=[])
    f = next((root / "context" / "candidate").glob("*.md"))
    dec = store.get(d.id)
    # Rewrite the timestamps in the form yaml parses into datetime objects
    # (unquoted, space separator) — semantically identical to the DB value.
    text = f.read_text()
    text = text.replace(
        f"created_at: '{dec.created_at.isoformat()}'",
        f"created_at: {dec.created_at.isoformat().replace('T', ' ')}",
    ).replace(
        f"updated_at: '{dec.updated_at.isoformat()}'",
        f"updated_at: {dec.updated_at.isoformat().replace('T', ' ')}",
    )
    f.write_text(text)
    res = import_bundle(store, repo="r", root=root)
    assert not any("created_at" in w or "updated_at" in w for w in res.warnings)


def test_generated_index_file_is_not_imported_as_a_decision(tmp_path):
    # `metatron files index` writes a generated listing (index.md) into
    # decisions/. It is a reserved artifact, not a concept document — it must
    # never be imported (least of all as a silently-created CANONICAL decision).
    store = _store(tmp_path)
    root = tmp_path / "mirror"
    (root / "context" / "decisions").mkdir(parents=True)
    (root / "context" / "decisions" / "index.md").write_text(
        "# Decision index\n\n> Generated — do not edit.\n"
    )
    res = import_bundle(store, repo="r", root=root)
    assert store.count() == 0
    assert res.warnings == []  # known artifact: skipped silently


def test_idless_file_without_type_is_skipped_with_warning(tmp_path):
    # A stray id-less markdown note in a status directory is not an OKF concept
    # (no `type` frontmatter) and must not become a decision.
    store = _store(tmp_path)
    root = tmp_path / "mirror"
    (root / "context" / "decisions").mkdir(parents=True)
    (root / "context" / "decisions" / "notes.md").write_text(
        "---\nauthor: someone\n---\n\n## Pattern\nstray note\n"
    )
    res = import_bundle(store, repo="r", root=root)
    assert store.count() == 0
    assert any("notes.md" in w and "type" in w for w in res.warnings)


def test_import_reads_legacy_metatron_bundle_without_config(tmp_path):
    # Bundles created before the context/ rename live under metatron/; with no
    # explicit configuration the importer must keep reading them.
    store = _store(tmp_path)
    root = tmp_path / "mirror"
    d_dir = root / "metatron" / "decisions"
    d_dir.mkdir(parents=True)
    (d_dir / "hand-authored.md").write_text(
        "---\ntype: Metatron Decision\nscope: web\nconfidence: high\n---\n\n"
        "## Pattern\nP.\n\n## Rationale\nR.\n")
    import_bundle(store, repo="r", root=root)
    assert store.count(repo="r", status=Status.CANONICAL) == 1


def test_roundtrip_with_custom_context_dir(tmp_path):
    # An explicitly configured directory name is honored by export and import.
    store = _store(tmp_path)
    d = store.add(Decision(repo="r", pattern="p", scope="a", rationale="x",
                           origin=Origin.HUMAN, status=Status.CANDIDATE))
    root = tmp_path / "mirror"
    export_bundle(store, repo="r", root=root, events=[], context_dir="kb")
    assert (root / "kb" / "candidate").is_dir()
    assert not (root / "context").exists()
    res = import_bundle(store, repo="r", root=root, context_dir="kb")
    assert res.conflicts == [] and store.get(d.id).status == Status.CANDIDATE
