"""Guards for the Docker image used to publish Metatron (e.g. to Glama.ai).

These don't build the image (that needs Docker); they protect the two properties
that are easy to break silently: the entrypoint must launch the MCP server, and the
build context must never bake secrets/local state into a public image.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_dockerfile_serves_the_mcp_server():
    dockerfile = (ROOT / "Dockerfile").read_text()
    assert "metatron" in dockerfile and "serve" in dockerfile
    # stdio MCP transport needs unbuffered output to stream cleanly
    assert "PYTHONUNBUFFERED" in dockerfile


def test_dockerignore_excludes_secrets_and_local_state():
    # COPY . . would otherwise bake the API key, the local DB, and the host venv
    # into a public image. This is the regression we never want to ship.
    ignore = (ROOT / ".dockerignore").read_text().splitlines()
    patterns = {line.strip() for line in ignore if line.strip() and not line.startswith("#")}
    assert ".env" in patterns
    assert any(p in patterns for p in ("*.db", "metatron.db"))
    assert ".venv" in patterns
    assert ".git" in patterns
