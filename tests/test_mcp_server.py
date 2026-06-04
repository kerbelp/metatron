"""Tests that the MCP server exposes and wires the two required tools."""

import asyncio

from metatron.events import Event, EventKind
from metatron.mcp_server.server import build_server
from metatron.models import Origin, Prior, Status
from metatron.storage.sqlite import SQLiteEventStore, SQLitePriorStore

REPO = "github.com/acme/app"


def _result(call):
    # FastMCP.call_tool returns (content_blocks, {"result": <return value>}).
    return call[1]["result"]


def test_server_exposes_the_expected_tools():
    server = build_server(SQLitePriorStore(":memory:"), REPO)
    names = {t.name for t in asyncio.run(server.list_tools())}
    assert names == {
        "get_priors_for_context",
        "submit_candidate_learning",
        "submit_feedback",
    }


def test_get_priors_output_carries_query_token_and_revision():
    store = SQLitePriorStore(":memory:")
    store.add(Prior(repo=REPO, pattern="a canonical rule", scope="app",
                    rationale="r", origin=Origin.BOOTSTRAP, status=Status.CANONICAL))
    server = build_server(store, REPO, SQLiteEventStore(":memory:"))
    out = _result(asyncio.run(server.call_tool(
        "get_priors_for_context",
        {"file_path_or_area": "app", "task_description": "anything"},
    )))
    assert "metatron:query" in out and "rev " in out


def test_submit_feedback_tool_captures_gap_without_creating_candidate():
    store = SQLitePriorStore(":memory:")
    events = SQLiteEventStore(":memory:")
    server = build_server(store, REPO, events)
    asyncio.run(server.call_tool("submit_feedback", {
        "what_was_missing": "credit path must mirror the order_created webhook",
        "missing_scope": "src/routes/api/order_created",
    }))
    # Capture only: no candidate yet (the refiner creates structured ones later).
    assert store.list(repo=REPO) == []
    fb = [e for e in events.list_events() if e.kind is EventKind.FEEDBACK]
    assert len(fb) == 1 and fb[0].handled is False
    assert "order_created" in fb[0].missing


def test_submit_feedback_tool_accepts_graded_ratings_by_index():
    store = SQLitePriorStore(":memory:")
    events = SQLiteEventStore(":memory:")
    # a prior query served two priors, so indices 1 and 2 resolve
    q = Event(repo=REPO, kind=EventKind.QUERY, prior_ids=["pa", "pb"])
    events.record(q)
    server = build_server(store, REPO, events)
    asyncio.run(server.call_tool("submit_feedback", {
        "query_id": q.id,
        "ratings": {"1": 10, "2": 2},
    }))
    fb = [e for e in events.list_events() if e.kind is EventKind.FEEDBACK][0]
    assert fb.ratings == {"pa": 10, "pb": 2}
    assert fb.helpful_prior_ids == ["pa"] and fb.unhelpful_prior_ids == ["pb"]


def test_ratings_influence_the_next_serving_order():
    # Two equally-relevant priors; after one is rated 10, it is served first.
    store = SQLitePriorStore(":memory:")
    events = SQLiteEventStore(":memory:")
    for tag in ("alpha", "beta"):  # tag words aren't in the task, so they don't sway keywords
        store.add(Prior(repo=REPO, pattern=f"webhook ledger handling {tag}", scope="src/api",
                        rationale="r", origin=Origin.BOOTSTRAP, status=Status.CANONICAL))
    server = build_server(store, REPO, events)
    args = {"file_path_or_area": "src/api", "task_description": "webhook ledger"}

    asyncio.run(server.call_tool("get_priors_for_context", args))  # records the query
    q = [e for e in events.list_events() if e.kind is EventKind.QUERY][0]
    beta_idx = next(i for i, pid in enumerate(q.prior_ids, start=1)
                    if store.get(pid).pattern.endswith("beta"))
    asyncio.run(server.call_tool("submit_feedback", {"query_id": q.id, "ratings": {str(beta_idx): 10}}))

    out = _result(asyncio.run(server.call_tool("get_priors_for_context", args)))
    assert out.index("beta") < out.index("alpha")  # the rated prior now leads


def test_get_priors_tool_returns_formatted_canonical_priors():
    store = SQLitePriorStore(":memory:")
    store.add(
        Prior(
            repo=REPO,
            pattern="serve only canonical priors",
            scope="app",
            rationale="curation gate",
            origin=Origin.BOOTSTRAP,
            status=Status.CANONICAL,
        )
    )
    server = build_server(store, REPO)
    out = _result(
        asyncio.run(
            server.call_tool(
                "get_priors_for_context",
                {"file_path_or_area": "app", "task_description": "anything"},
            )
        )
    )
    assert "serve only canonical priors" in out


def test_get_priors_on_empty_store_serves_gracefully():
    # A freshly built image serves before anything is ingested. The server must
    # boot and answer queries (empty result), never error — this is what lets the
    # container pass an MCP client's introspection checks on first run.
    server = build_server(SQLitePriorStore(":memory:"), REPO, SQLiteEventStore(":memory:"))
    out = _result(asyncio.run(server.call_tool(
        "get_priors_for_context",
        {"file_path_or_area": "src/anything", "task_description": "do a thing"},
    )))
    assert "No matching priors" in out


def test_submit_tool_persists_a_candidate_and_returns_its_id():
    store = SQLitePriorStore(":memory:")
    server = build_server(store, REPO)
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


def test_query_records_a_usage_event():
    store = SQLitePriorStore(":memory:")
    prior = Prior(
        repo=REPO, pattern="p", scope="app", rationale="r",
        origin=Origin.BOOTSTRAP, status=Status.CANONICAL,
    )
    store.add(prior)
    events = SQLiteEventStore(":memory:")
    server = build_server(store, REPO, events)

    asyncio.run(
        server.call_tool(
            "get_priors_for_context",
            {"file_path_or_area": "app", "task_description": "do a thing"},
        )
    )

    recorded = events.list_events()
    assert len(recorded) == 1
    e = recorded[0]
    assert e.kind is EventKind.QUERY
    assert e.area == "app"
    assert e.result_count == 1
    assert prior.id in e.prior_ids


def test_submit_records_a_usage_event():
    store = SQLitePriorStore(":memory:")
    events = SQLiteEventStore(":memory:")
    server = build_server(store, REPO, events)

    asyncio.run(
        server.call_tool(
            "submit_candidate_learning",
            {"pattern": "p", "scope": "app/api", "rationale": "r"},
        )
    )

    recorded = events.list_events()
    assert [e.kind for e in recorded] == [EventKind.SUBMIT]
    assert recorded[0].area == "app/api"


def test_event_logging_is_optional():
    # No event store -> no crash, tools still work.
    store = SQLitePriorStore(":memory:")
    server = build_server(store, REPO)
    asyncio.run(
        server.call_tool(
            "get_priors_for_context",
            {"file_path_or_area": "app", "task_description": "x"},
        )
    )
