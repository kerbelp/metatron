from pathlib import Path
from metatron.filesfirst.lint import lint_tree


def _write(d: Path, name: str, body: str):
    (d / name).write_text(body, encoding="utf-8")


def test_clean_tree_has_no_errors(tmp_path):
    _write(tmp_path, "token-refresh-strategy.md",
           "---\nid: token-refresh-strategy\ntype: decision\nstatus: candidate\ntitle: T\n---\nbody\n")
    assert lint_tree(tmp_path) == []


def test_flags_missing_required_field(tmp_path):
    _write(tmp_path, "x.md", "---\nid: x\ntitle: T\n---\nbody\n")  # no type
    errs = lint_tree(tmp_path)
    assert any("type" in e.message for e in errs)


def test_idless_status_less_file_is_valid(tmp_path):
    # Identity is the filename slug; status comes from the directory. Only
    # `type` is required, so a skill-authored concept lints clean.
    _write(tmp_path, "x.md",
           "---\ntype: Metatron Decision\nscope: web\n---\n\n## Pattern\nP\n\n## Rationale\nR\n")
    assert lint_tree(tmp_path) == []


def test_flags_bad_status_value(tmp_path):
    _write(tmp_path, "x.md", "---\nid: x\ntype: decision\nstatus: maybe\ntitle: T\n---\nbody\n")
    errs = lint_tree(tmp_path)
    assert any("invalid status" in e.message for e in errs)


def test_explicit_id_can_differ_from_readable_filename(tmp_path):
    _write(tmp_path, "token-refresh-strategy.md",
           "---\nid: 3e703f65-f80c-4c8f-b70c-f68436676421\n"
           "type: decision\nstatus: candidate\ntitle: T\n---\nb\n")
    assert lint_tree(tmp_path) == []


def test_flags_uuid_filename_as_uninformative(tmp_path):
    decision_id = "3e703f65-f80c-4c8f-b70c-f68436676421"
    _write(tmp_path, f"{decision_id}.md",
           f"---\nid: {decision_id}\ntype: decision\nstatus: candidate\ntitle: T\n---\nb\n")
    errs = lint_tree(tmp_path)
    assert any("UUID filename" in e.message and "readable slug" in e.message for e in errs)


def test_flags_duplicate_ids(tmp_path):
    # Two differently named files may carry the same durable id, but that is
    # still an identity collision.
    _write(tmp_path, "dup.md", "---\nid: dup\ntype: decision\nstatus: candidate\ntitle: T\n---\nb\n")
    _write(tmp_path, "dup2.md", "---\nid: dup\ntype: decision\nstatus: candidate\ntitle: T\n---\nb\n")
    errs = lint_tree(tmp_path)
    assert any("duplicate id" in e.message for e in errs)


def test_flags_non_list_keywords(tmp_path):
    # A scalar `keywords: auth` is invalid — keywords must be a YAML list.
    _write(tmp_path, "x.md",
           "---\nid: x\ntype: decision\nstatus: candidate\ntitle: T\nkeywords: auth\n---\nb\n")
    errs = lint_tree(tmp_path)
    assert any("keywords must be a list" in e.message for e in errs)


def test_reserved_filenames_skipped(tmp_path):
    _write(tmp_path, "index.md", "# generated\n")
    _write(tmp_path, "log.md", "# log\n")
    assert lint_tree(tmp_path) == []
