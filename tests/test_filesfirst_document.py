from pathlib import Path
from metatron.filesfirst.document import parse_decision_file, decision_ids


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
    assert doc.id is None
    assert doc.status is None


def test_decision_ids_collects_ids_and_skips_reserved(tmp_path):
    (tmp_path / "a.md").write_text(
        "---\nid: a\ntype: decision\nstatus: candidate\ntitle: A\n---\nb\n", encoding="utf-8")
    (tmp_path / "index.md").write_text("# generated\n", encoding="utf-8")
    assert decision_ids(tmp_path) == {"a"}
