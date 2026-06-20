from pathlib import Path
from metatron.filesfirst.lint import lint_tree


def _write(d: Path, name: str, body: str):
    (d / name).write_text(body, encoding="utf-8")


def test_clean_tree_has_no_errors(tmp_path):
    _write(tmp_path, "token-refresh-strategy.md",
           "---\nid: token-refresh-strategy\ntype: decision\nstatus: candidate\ntitle: T\n---\nbody\n")
    assert lint_tree(tmp_path) == []


def test_flags_missing_required_field(tmp_path):
    _write(tmp_path, "x.md", "---\nid: x\ntype: decision\ntitle: T\n---\nbody\n")  # no status
    errs = lint_tree(tmp_path)
    assert any("status" in e.message for e in errs)


def test_flags_bad_status_value(tmp_path):
    _write(tmp_path, "x.md", "---\nid: x\ntype: decision\nstatus: maybe\ntitle: T\n---\nbody\n")
    errs = lint_tree(tmp_path)
    assert any("invalid status" in e.message for e in errs)


def test_flags_id_filename_mismatch(tmp_path):
    _write(tmp_path, "wrong-name.md", "---\nid: x\ntype: decision\nstatus: candidate\ntitle: T\n---\nb\n")
    errs = lint_tree(tmp_path)
    assert any("must match filename" in e.message for e in errs)


def test_flags_duplicate_ids(tmp_path):
    # Two files both claiming id `dup`. (dup2.md also trips the id/slug-mismatch
    # rule; that's fine — we only assert the duplicate-id branch fires.)
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
