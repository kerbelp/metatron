from pathlib import Path
from metatron.filesfirst.document import parse_decision_file, decision_ids, write_machine_fields


SAMPLE = """---
id: token-refresh-strategy
type: decision
status: candidate
title: Refresh tokens server-side
keywords: [auth, tokens]
---

We refresh tokens server-side because clients leak them.
"""


def test_parse_exposes_frontmatter_and_body():
    doc = parse_decision_file(Path("token-refresh-strategy.md"), SAMPLE)
    assert doc.id == "token-refresh-strategy"
    assert doc.status == "candidate"
    assert doc.frontmatter["keywords"] == ["auth", "tokens"]
    assert "server-side" in doc.body


def test_parse_missing_frontmatter_is_empty_not_crash():
    doc = parse_decision_file(Path("x.md"), "just prose, no frontmatter")
    assert doc.id == "x"          # identity falls back to the filename slug
    assert doc.status is None


def test_decision_ids_collects_ids_and_skips_reserved(tmp_path):
    (tmp_path / "a.md").write_text(
        "---\nid: a\ntype: decision\nstatus: candidate\ntitle: A\n---\nb\n", encoding="utf-8")
    (tmp_path / "index.md").write_text("# generated\n", encoding="utf-8")
    assert decision_ids(tmp_path) == {"a"}


def test_write_machine_fields_preserves_human_fields_and_body(tmp_path):
    p = tmp_path / "d.md"
    p.write_text(
        "---\nid: d\ntype: decision\nstatus: canonical\ntitle: T\n"
        "keywords: [auth]\n---\n\n## Decision\n\nProse body.\n", encoding="utf-8")
    write_machine_fields(p, {"references": 5, "violations": 1, "last_applied": "2026-06-18"})
    text = p.read_text(encoding="utf-8")
    assert "references: 5" in text
    assert "violations: 1" in text
    assert "id: d" in text and "title: T" in text   # human fields kept
    assert "Prose body." in text                      # body kept


def test_write_machine_fields_does_not_reflow_human_fields(tmp_path):
    # A CI count update must not rewrite human-owned formatting (flow-style list
    # stays flow-style); only the machine-field lines change.
    p = tmp_path / "d.md"
    p.write_text(
        "---\nid: d\ntype: decision\nstatus: canonical\ntitle: T\n"
        "keywords: [auth, tokens]\n---\n\nBody.\n", encoding="utf-8")
    write_machine_fields(p, {"references": 2})
    text = p.read_text(encoding="utf-8")
    assert "keywords: [auth, tokens]" in text
    assert "references: 2" in text


def test_write_machine_fields_is_idempotent(tmp_path):
    # Re-applying the same fields replaces the line rather than duplicating it.
    p = tmp_path / "d.md"
    p.write_text(
        "---\nid: d\ntype: decision\nstatus: canonical\ntitle: T\n---\nb\n", encoding="utf-8")
    write_machine_fields(p, {"references": 1})
    first = p.read_text(encoding="utf-8")
    write_machine_fields(p, {"references": 1})
    assert p.read_text(encoding="utf-8") == first
    assert first.count("references:") == 1
