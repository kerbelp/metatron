import json

from metatron.mcp_server import service

CONTRACT = """---
type: Metatron Verification
scope: services/auth
---

## Checks
### login  [tags: smoke]
Action:
    curl -s localhost/login
Expect:
- exit 0

## Failure Means
- gateway down
"""


def _seed(tmp_path):
    vdir = tmp_path / "context" / "verification"
    vdir.mkdir(parents=True)
    (vdir / "auth.md").write_text(CONTRACT, encoding="utf-8")
    return tmp_path


def test_get_verification_returns_scoped_json(tmp_path):
    _seed(tmp_path)
    out = service.get_verification("services/auth", root=str(tmp_path))
    data = json.loads(out)
    assert data[0]["scope"] == "services/auth"
    assert data[0]["failure_means"] == ["gateway down"]
    assert data[0]["checks"][0]["expects"] == ["exit 0"]


def test_get_verification_no_match(tmp_path):
    _seed(tmp_path)
    out = service.get_verification("services/billing", root=str(tmp_path))
    assert out == "No matching verification contracts."


def test_get_verification_template_is_the_skeleton():
    tpl = service.get_verification_template()
    assert "type: Metatron Verification" in tpl
    assert "## Checks" in tpl


def test_server_exposes_readonly_verification_tools_only():
    # The security fence: the server may read verification contracts but must
    # never expose a tool that writes or executes one.
    import inspect

    from metatron.mcp_server import server as server_module

    src = inspect.getsource(server_module.build_server)
    assert "def get_verification(" in src
    assert "def get_verification_template(" in src
    assert "def run_verification(" not in src
    assert "def write_verification(" not in src
