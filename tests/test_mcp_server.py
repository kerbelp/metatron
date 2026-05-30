"""Tests that the MCP server exposes and wires the two required tools."""

import asyncio

from metatron.mcp_server.server import build_server
from metatron.models import Origin, Prior, Status
from metatron.storage.sqlite import SQLitePriorStore


def _result(call):
    # FastMCP.call_tool returns (content_blocks, {"result": <return value>}).
    return call[1]["result"]


def test_server_exposes_exactly_the_two_required_tools():
    server = build_server(SQLitePriorStore(":memory:"))
    names = {t.name for t in asyncio.run(server.list_tools())}
    assert names == {"get_priors_for_context", "submit_candidate_learning"}


def test_get_priors_tool_returns_formatted_canonical_priors():
    store = SQLitePriorStore(":memory:")
    store.add(
        Prior(
            pattern="serve only canonical priors",
            scope="app",
            rationale="curation gate",
            origin=Origin.BOOTSTRAP,
            status=Status.CANONICAL,
        )
    )
    server = build_server(store)
    out = _result(
        asyncio.run(
            server.call_tool(
                "get_priors_for_context",
                {"file_path_or_area": "app", "task_description": "anything"},
            )
        )
    )
    assert "serve only canonical priors" in out


def test_submit_tool_persists_a_candidate_and_returns_its_id():
    store = SQLitePriorStore(":memory:")
    server = build_server(store)
    new_id = _result(
        asyncio.run(
            server.call_tool(
                "submit_candidate_learning",
                {
                    "pattern": "log request ids",
                    "scope": "app/api",
                    "rationale": "traceability",
                },
            )
        )
    )
    stored = store.get(new_id)
    assert stored is not None
    assert stored.status is Status.CANDIDATE
    assert stored.origin is Origin.AGENT_SUBMITTED
