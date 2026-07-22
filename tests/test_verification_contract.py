from pathlib import Path

from metatron.verification.contract import parse_assertion, parse_contract

SAMPLE = """---
type: Metatron Verification
scope: services/auth
confidence: high
source_refs:
  - services/auth/login.py
---

## Assumptions
- Postgres on localhost:5432
- a wrapped assumption that spills
  onto a second line

## Setup
    echo one
    echo two

## Checks
### Happy path  [tags: smoke, critical-path]
Action:
    curl -s localhost/login
Expect:
- exit 0
- stdout jsonpath $.tokenType == Bearer
- stdout jsonpath $.accessToken exists

### Sad path  [tags: security]
Action:
    curl -s localhost/login-bad
Expect:
- stderr contains denied

## Failure Means
- token missing means seed mismatch

## Judged invariants  [--judge]
- judge: help text lists every format

## Teardown
    echo clean
"""


def test_parses_sections_and_frontmatter():
    c = parse_contract(Path("auth.md"), SAMPLE)
    assert c.scope == "services/auth"
    assert c.frontmatter["confidence"] == "high"
    assert c.setup == "echo one\necho two"
    assert c.teardown == "echo clean"
    assert c.failure_means == ["token missing means seed mismatch"]
    assert c.judged == ["help text lists every format"]


def test_wrapped_bullet_folds():
    c = parse_contract(Path("auth.md"), SAMPLE)
    assert c.assumptions == [
        "Postgres on localhost:5432",
        "a wrapped assumption that spills onto a second line",
    ]


def test_checks_actions_and_tags():
    c = parse_contract(Path("auth.md"), SAMPLE)
    assert [chk.name for chk in c.checks] == ["Happy path", "Sad path"]
    assert c.checks[0].tags == ["smoke", "critical-path"]
    # the first check's action is not clobbered by the second (regression guard)
    assert c.checks[0].action == "curl -s localhost/login"
    assert c.checks[1].action == "curl -s localhost/login-bad"


def test_assertion_grammar():
    assert parse_assertion("exit 0").kind == "exit"
    assert parse_assertion("exit 2").code == 2
    a = parse_assertion("stdout contains wrote")
    assert (a.kind, a.stream, a.text) == ("contains", "stdout", "wrote")
    assert parse_assertion("contains wrote").stream == "stdout"  # default stream
    assert parse_assertion("stderr matches ^ok$").kind == "matches"
    jp = parse_assertion("stdout jsonpath $.a.b == 3")
    assert (jp.kind, jp.path, jp.op, jp.value) == ("jsonpath", "$.a.b", "==", "3")
    assert parse_assertion("jsonpath $.x exists").op == "exists"
    assert parse_assertion("shell test -f x").kind == "shell"
    assert parse_assertion("nonsense line").kind == "invalid"


def test_to_dict_is_json_shaped():
    d = parse_contract(Path("auth.md"), SAMPLE).to_dict()
    assert d["scope"] == "services/auth"
    assert d["checks"][0]["expects"][0] == "exit 0"
    assert d["failure_means"] == ["token missing means seed mismatch"]
