"""Tests that the MCP server exposes and wires the two required tools."""

import asyncio

from metatron.events import Event, EventKind
from metatron.mcp_server.server import build_server
from metatron.models import Origin, Decision, Status
from metatron.storage.sqlite import SQLiteEventStore, SQLiteDecisionStore

REPO = "github.com/acme/app"


def _result(call):
    # FastMCP.call_tool returns (content_blocks, {"result": <return value>}).
    return call[1]["result"]


def test_server_exposes_the_expected_tools():
    server = build_server(SQLiteDecisionStore(":memory:"), REPO)
    names = {t.name for t in asyncio.run(server.list_tools())}
    assert names == {
        "get_decisions_for_context",
        "submit_candidate_decision",
        "submit_feedback",
    }


def test_every_tool_parameter_carries_a_schema_description():
    # MCP clients (and quality scorers like Glama) read parameter docs from the
    # JSON inputSchema, not from the Python docstring's Args section. Each param
    # must therefore declare a Field(description=...) so it reaches the schema.
    server = build_server(SQLiteDecisionStore(":memory:"), REPO)
    for tool in asyncio.run(server.list_tools()):
        props = tool.inputSchema["properties"]
        assert props, f"{tool.name} exposes no parameters"
        for name, schema in props.items():
            assert schema.get("description", "").strip(), (
                f"{tool.name}.{name} is missing a schema description"
            )


def test_events_are_stamped_with_the_local_identity():
    from metatron.identity import Identity

    store = SQLiteDecisionStore(":memory:")
    events = SQLiteEventStore(":memory:")
    ident = Identity(actor_id="a1", email="dev@corp.com", display_name="Dev")
    server = build_server(store, REPO, events, identity=ident)
    asyncio.run(server.call_tool(
        "get_decisions_for_context",
        {"file_path_or_area": "app", "task_description": "x"},
    ))
    e = events.list_events()[0]
    assert e.actor_id == "a1"
    assert e.actor_email == "dev@corp.com"
    assert e.actor_name == "Dev"


def test_events_are_anonymous_without_identity():
    store = SQLiteDecisionStore(":memory:")
    events = SQLiteEventStore(":memory:")
    server = build_server(store, REPO, events)  # no identity
    asyncio.run(server.call_tool(
        "get_decisions_for_context",
        {"file_path_or_area": "app", "task_description": "x"},
    ))
    assert events.list_events()[0].actor_id == ""


def test_get_decisions_output_carries_query_token_and_revision():
    store = SQLiteDecisionStore(":memory:")
    store.add(Decision(repo=REPO, pattern="a canonical rule", scope="app",
                    rationale="r", origin=Origin.BOOTSTRAP, status=Status.CANONICAL))
    server = build_server(store, REPO, SQLiteEventStore(":memory:"))
    out = _result(asyncio.run(server.call_tool(
        "get_decisions_for_context",
        {"file_path_or_area": "app", "task_description": "anything"},
    )))
    assert "metatron:query" in out and "rev " in out


def test_submit_feedback_tool_captures_gap_without_creating_candidate():
    store = SQLiteDecisionStore(":memory:")
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
    store = SQLiteDecisionStore(":memory:")
    events = SQLiteEventStore(":memory:")
    # a decision query served two decisions, so indices 1 and 2 resolve
    q = Event(repo=REPO, kind=EventKind.QUERY, decision_ids=["pa", "pb"])
    events.record(q)
    server = build_server(store, REPO, events)
    asyncio.run(server.call_tool("submit_feedback", {
        "query_id": q.id,
        "ratings": {"1": 10, "2": 2},
    }))
    fb = [e for e in events.list_events() if e.kind is EventKind.FEEDBACK][0]
    assert fb.ratings == {"pa": 10, "pb": 2}
    assert fb.helpful_decision_ids == ["pa"] and fb.unhelpful_decision_ids == ["pb"]


def test_ratings_influence_the_next_serving_order():
    # Two equally-relevant decisions; after one is rated 10, it is served first.
    store = SQLiteDecisionStore(":memory:")
    events = SQLiteEventStore(":memory:")
    for tag in ("alpha", "beta"):  # tag words aren't in the task, so they don't sway keywords
        store.add(Decision(repo=REPO, pattern=f"webhook ledger handling {tag}", scope="src/api",
                        rationale="r", origin=Origin.BOOTSTRAP, status=Status.CANONICAL))
    server = build_server(store, REPO, events)
    args = {"file_path_or_area": "src/api", "task_description": "webhook ledger"}

    asyncio.run(server.call_tool("get_decisions_for_context", args))  # records the query
    q = [e for e in events.list_events() if e.kind is EventKind.QUERY][0]
    beta_idx = next(i for i, pid in enumerate(q.decision_ids, start=1)
                    if store.get(pid).pattern.endswith("beta"))
    asyncio.run(server.call_tool("submit_feedback", {"query_id": q.id, "ratings": {str(beta_idx): 10}}))

    out = _result(asyncio.run(server.call_tool("get_decisions_for_context", args)))
    assert out.index("beta") < out.index("alpha")  # the rated decision now leads


def test_get_decisions_tool_returns_formatted_canonical_decisions():
    store = SQLiteDecisionStore(":memory:")
    store.add(
        Decision(
            repo=REPO,
            pattern="serve only canonical decisions",
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
                "get_decisions_for_context",
                {"file_path_or_area": "app", "task_description": "anything"},
            )
        )
    )
    assert "serve only canonical decisions" in out


def test_get_decisions_on_empty_store_serves_gracefully():
    # A freshly built image serves before anything is ingested. The server must
    # boot and answer queries (empty result), never error — this is what lets the
    # container pass an MCP client's introspection checks on first run.
    server = build_server(SQLiteDecisionStore(":memory:"), REPO, SQLiteEventStore(":memory:"))
    out = _result(asyncio.run(server.call_tool(
        "get_decisions_for_context",
        {"file_path_or_area": "src/anything", "task_description": "do a thing"},
    )))
    assert "No matching decisions" in out


def test_submit_tool_persists_a_candidate_and_returns_its_id():
    store = SQLiteDecisionStore(":memory:")
    server = build_server(store, REPO)
    new_id = _result(
        asyncio.run(
            server.call_tool(
                "submit_candidate_decision",
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
    store = SQLiteDecisionStore(":memory:")
    decision = Decision(
        repo=REPO, pattern="p", scope="app", rationale="r",
        origin=Origin.BOOTSTRAP, status=Status.CANONICAL,
    )
    store.add(decision)
    events = SQLiteEventStore(":memory:")
    server = build_server(store, REPO, events)

    asyncio.run(
        server.call_tool(
            "get_decisions_for_context",
            {"file_path_or_area": "app", "task_description": "do a thing"},
        )
    )

    recorded = events.list_events()
    assert len(recorded) == 1
    e = recorded[0]
    assert e.kind is EventKind.QUERY
    assert e.area == "app"
    assert e.result_count == 1
    assert decision.id in e.decision_ids


def test_submit_records_a_usage_event():
    store = SQLiteDecisionStore(":memory:")
    events = SQLiteEventStore(":memory:")
    server = build_server(store, REPO, events)

    asyncio.run(
        server.call_tool(
            "submit_candidate_decision",
            {"pattern": "p", "scope": "app/api", "rationale": "r"},
        )
    )

    recorded = events.list_events()
    assert [e.kind for e in recorded] == [EventKind.SUBMIT]
    assert recorded[0].area == "app/api"


def test_event_logging_is_optional():
    # No event store -> no crash, tools still work.
    store = SQLiteDecisionStore(":memory:")
    server = build_server(store, REPO)
    asyncio.run(
        server.call_tool(
            "get_decisions_for_context",
            {"file_path_or_area": "app", "task_description": "x"},
        )
    )
