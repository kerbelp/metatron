import io

from metatron.cli import main


def _run(argv, cwd):
    out = io.StringIO()
    code = main(argv, out=out)
    return code, out.getvalue()


def test_template_prints_skeleton(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    code, text = _run(["verification", "template"], tmp_path)
    assert code == 0
    assert "type: Metatron Verification" in text
    assert "## Failure Means" in text


def test_setup_then_run_green(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    code, _ = _run(["verification", "setup", "."], tmp_path)
    assert code == 0
    code, text = _run(["verification", "run"], tmp_path)
    assert code == 0
    assert "PASS:" in text


def test_new_scaffolds_into_verification(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    code, text = _run(
        ["verification", "new", "widget", "--scope", "services/widget"], tmp_path)
    assert code == 0
    created = tmp_path / "context" / "verification" / "widget.md"
    assert created.exists()
    assert "services/widget" in created.read_text()


def test_new_refuses_overwrite(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _run(["verification", "new", "widget", "--scope", "s"], tmp_path)
    code, text = _run(["verification", "new", "widget", "--scope", "s"], tmp_path)
    assert code == 1
    assert "refusing to overwrite" in text


def test_run_dry_run_executes_nothing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _run(["verification", "setup", "."], tmp_path)
    code, text = _run(["verification", "run", "--dry-run"], tmp_path)
    assert code == 0
    assert "check:" in text
    # a real run would have created and cleaned ./_verify; dry-run leaves nothing
    assert not (tmp_path / "_verify").exists()


def test_run_nonzero_exit_on_failure(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    vdir = tmp_path / "context" / "verification"
    vdir.mkdir(parents=True)
    (vdir / "bad.md").write_text("""---
type: Metatron Verification
scope: x
---

## Checks
### fails
Action:
    printf actual
Expect:
- stdout contains expected

## Failure Means
- output differs
""", encoding="utf-8")
    code, text = _run(["verification", "run"], tmp_path)
    assert code == 1
    assert "FAIL" in text
    assert "Failure Means" in text


def test_audit_reports_and_exits_nonzero(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    vdir = tmp_path / "context" / "verification"
    vdir.mkdir(parents=True)
    (vdir / "bad.md").write_text("""---
type: Metatron Decision
---

## Checks
### c
Action:
    echo hi
Expect:
- gibberish
""", encoding="utf-8")
    code, text = _run(["verification", "audit"], tmp_path)
    assert code == 1
    assert "problem(s) found" in text
