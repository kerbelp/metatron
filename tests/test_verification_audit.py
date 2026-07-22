from metatron.verification.audit import audit_dir


def _write(d, name, text):
    p = d / f"{name}.md"
    p.write_text(text, encoding="utf-8")
    return p


def test_clean_contract_has_no_errors(tmp_path):
    (tmp_path / "real.py").write_text("x = 1", encoding="utf-8")
    _write(tmp_path, "ok", """---
type: Metatron Verification
scope: cli/x
source_refs:
  - real.py
---

## Checks
### c
Action:
    echo hi
Expect:
- exit 0
""")
    assert audit_dir(tmp_path, repo_root=tmp_path) == []


def test_flags_wrong_type_missing_scope_and_bad_assertions(tmp_path):
    _write(tmp_path, "bad", """---
type: Metatron Decision
---

## Checks
### c
Action:
    echo hi
Expect:
- totally not an assertion
""")
    messages = [e.message for e in audit_dir(tmp_path, repo_root=tmp_path)]
    assert any("type must be" in m for m in messages)
    assert any("missing required field: scope" in m for m in messages)
    assert any("unparseable assertion" in m for m in messages)


def test_flags_dangling_source_ref_and_empty_check(tmp_path):
    _write(tmp_path, "dangling", """---
type: Metatron Verification
scope: cli/x
source_refs:
  - does/not/exist.py
---

## Checks
### no action here
Expect:
- exit 0
""")
    messages = [e.message for e in audit_dir(tmp_path, repo_root=tmp_path)]
    assert any("missing path" in m for m in messages)
    assert any("has no Action" in m for m in messages)
