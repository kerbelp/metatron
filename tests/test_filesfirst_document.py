from pathlib import Path
from metatron.filesfirst.document import parse_decision_file


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
