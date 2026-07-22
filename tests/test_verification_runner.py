from pathlib import Path

from metatron.verification.contract import parse_contract
from metatron.verification.report import render_json, render_junit, render_text
from metatron.verification.runner import plan, run_contracts

PASSING = """---
type: Metatron Verification
scope: cli/demo
---

## Setup
    printf 'hello world' > marker.txt

## Checks
### reads the marker  [tags: smoke]
Action:
    cat marker.txt
Expect:
- exit 0
- stdout contains hello
- stdout matches wor.d

### json body  [tags: api]
Action:
    printf '{"tokenType":"Bearer","n":3}'
Expect:
- stdout jsonpath $.tokenType == Bearer
- stdout jsonpath $.n == 3
- stdout jsonpath $.tokenType exists

## Failure Means
- broken marker means setup did not run

## Teardown
    rm -f marker.txt
"""

FAILING = """---
type: Metatron Verification
scope: cli/demo
---

## Checks
### expects the wrong thing
Action:
    printf 'actual'
Expect:
- stdout contains expected

## Failure Means
- the tool printed something other than 'expected'
"""


def _contract(text):
    return parse_contract(Path("c.md"), text)


def test_passing_contract(tmp_path):
    report = run_contracts([_contract(PASSING)], cwd=tmp_path)
    assert report.passed
    assert report.total_checks == 2
    assert report.failed_checks == 0
    # teardown removed the marker
    assert not (tmp_path / "marker.txt").exists()


def test_failing_contract_surfaces_failure_means(tmp_path):
    report = run_contracts([_contract(FAILING)], cwd=tmp_path)
    assert not report.passed
    text = render_text(report)
    assert "FAIL" in text
    assert "Failure Means:" in text
    assert "other than 'expected'" in text


def test_tag_filter_skips_non_matching(tmp_path):
    report = run_contracts([_contract(PASSING)], cwd=tmp_path, tags=["smoke"])
    checks = report.contracts[0].checks
    ran = [c for c in checks if not c.skipped]
    skipped = [c for c in checks if c.skipped]
    assert [c.name for c in ran] == ["reads the marker"]
    assert [c.name for c in skipped] == ["json body"]


def test_dry_run_plan_executes_nothing(tmp_path):
    text = plan([_contract(PASSING)])
    assert "cat marker.txt" in text
    assert "expect: exit 0" in text
    # nothing ran, so no marker file was created
    assert not (tmp_path / "marker.txt").exists()


def test_setup_failure_aborts_checks(tmp_path):
    c = _contract("""---
type: Metatron Verification
scope: x
---

## Setup
    exit 7

## Checks
### never runs
Action:
    echo hi
Expect:
- exit 0
""")
    report = run_contracts([c], cwd=tmp_path)
    cr = report.contracts[0]
    assert not cr.setup_ok
    assert cr.checks == []
    assert not report.passed


def test_report_formats(tmp_path):
    report = run_contracts([_contract(PASSING)], cwd=tmp_path)
    assert '"passed": true' in render_json(report)
    junit = render_junit(report)
    assert junit.startswith("<?xml")
    assert 'testsuite name="c"' in junit
