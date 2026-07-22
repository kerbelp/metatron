from pathlib import Path

from metatron.verification.discover import iter_contracts, scope_matches, select

CONTRACT = """---
type: {type}
scope: {scope}
---

## Checks
### c  [tags: {tags}]
Action:
    echo hi
Expect:
- exit 0
"""


def _write(d: Path, name, scope, type_="Metatron Verification", tags="smoke"):
    (d / f"{name}.md").write_text(
        CONTRACT.format(type=type_, scope=scope, tags=tags), encoding="utf-8")


def test_iter_only_typed_non_reserved(tmp_path):
    _write(tmp_path, "auth", "services/auth")
    _write(tmp_path, "notes", "x", type_="Metatron Decision")  # wrong type: ignored
    (tmp_path / "index.md").write_text("# listing", encoding="utf-8")  # reserved
    slugs = [c.slug for c in iter_contracts(tmp_path)]
    assert slugs == ["auth"]


def test_scope_matches_both_directions():
    assert scope_matches("services/auth", "services/auth")
    assert scope_matches("services/auth/login", "services/auth")   # under
    assert scope_matches("services", "services/auth")              # covers
    assert not scope_matches("services/billing", "services/auth")
    assert scope_matches("anything", "")                           # empty = all


def test_select_by_scope_and_tags(tmp_path):
    _write(tmp_path, "auth", "services/auth", tags="smoke, critical-path")
    _write(tmp_path, "billing", "services/billing", tags="regression")
    contracts = iter_contracts(tmp_path)
    assert [c.slug for c in select(contracts, scope="services/auth")] == ["auth"]
    assert [c.slug for c in select(contracts, tags=["regression"])] == ["billing"]
    assert select(contracts, scope="services/auth", tags=["regression"]) == []
