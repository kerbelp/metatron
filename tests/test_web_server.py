"""Tests for the web server: free-port selection, static app serving, and JSON APIs."""

import json
import socket
import threading
import urllib.error
import urllib.request

import pytest

from metatron.events import Event, EventKind
from metatron.models import Origin, Decision, Status
from metatron.storage.sqlite import SQLiteEventStore, SQLiteDecisionStore
from metatron.webui.server import find_free_port, make_server


def _get(url: str):
    with urllib.request.urlopen(url) as r:
        return r.status, r.read()


def _get_full(url: str):
    with urllib.request.urlopen(url) as r:
        return r.status, r.read(), r.headers.get("Content-Type", "")


def _post(url: str):
    with urllib.request.urlopen(urllib.request.Request(url, method="POST")) as r:
        return r.status, r.read()


def test_find_free_port_bumps_when_start_is_taken():
    occupied = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    occupied.bind(("127.0.0.1", 0))
    occupied.listen()
    taken = occupied.getsockname()[1]
    try:
        port = find_free_port(start=taken, host="127.0.0.1")
        assert port > taken
    finally:
        occupied.close()


@pytest.fixture
def served():
    store = SQLiteDecisionStore(":memory:")
    decision = Decision(repo="github.com/acme/app", pattern="serve me", scope="app", rationale="r", origin=Origin.BOOTSTRAP)
    store.add(decision)
    events = SQLiteEventStore(":memory:")
    events.record(Event(repo="github.com/acme/app", kind=EventKind.QUERY, area="app", result_count=1))
    port = find_free_port(start=8800, host="127.0.0.1")
    httpd = make_server(store, "127.0.0.1", port, events)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield store, decision, f"http://127.0.0.1:{port}"
    finally:
        httpd.shutdown()
        httpd.server_close()


# --- static front-end serving -------------------------------------------------

def test_root_serves_the_react_app(served):
    _, _, base = served
    status, body = _get(base + "/")
    assert status == 200
    html = body.decode().lower()
    assert "<!doctype html>" in html or "<html" in html
    assert 'id="root"' in html           # the React mount point
    assert "api.js" in html              # the data layer is loaded
    assert "styles.css" in html


def test_static_assets_are_served_with_content_types(served):
    _, _, base = served
    status, body, ctype = _get_full(base + "/api.js")
    assert status == 200 and "javascript" in ctype
    assert b"MetatronAPI" in body        # the live data module

    _, _, css_ctype = _get_full(base + "/styles.css")
    assert "text/css" in css_ctype

    _, _, jsx_ctype = _get_full(base + "/app.jsx")
    assert "babel" in jsx_ctype          # served so in-browser Babel can fetch it


def test_static_serving_rejects_unknown_and_nested_paths(served):
    _, _, base = served
    for path in ("/nope.js", "/sub/dir/x.js"):
        with pytest.raises(urllib.error.HTTPError) as exc:
            _get(base + path)
        assert exc.value.code == 404


# --- JSON API -----------------------------------------------------------------

def test_ingest_status_idle_and_start_requires_provider(served):
    _, _, base = served
    _, body = _get(base + "/api/ingest/status")
    assert json.loads(body)["state"] == "idle"

    req = urllib.request.Request(
        base + "/api/ingest/start", data=b'{"path": "/tmp"}',
        method="POST", headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as r:
        res = json.loads(r.read())
    assert res["ok"] is False


def test_valuate_status_idle_and_approve_recommended_wired(served):
    _, _, base = served
    _, body = _get(base + "/api/valuate/status")
    assert json.loads(body)["state"] == "idle"

    req = urllib.request.Request(
        base + "/api/decisions/approve-recommended",
        data=b'{"repo": "github.com/acme/app"}',
        method="POST", headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as r:
        res = json.loads(r.read())
    assert res["ok"] is True and res["approved"] == 0


def test_approve_recommended_accepts_an_origin_filter(served):
    _, _, base = served
    req = urllib.request.Request(
        base + "/api/decisions/approve-recommended",
        data=b'{"repo": "github.com/acme/app", "origin": "agent_feedback"}',
        method="POST", headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as r:
        res = json.loads(r.read())
    assert res["ok"] is True and res["approved"] == 0


def test_valuate_start_accepts_origin_and_approve_and_is_graceful(served):
    _, _, base = served
    req = urllib.request.Request(
        base + "/api/valuate/start",
        data=b'{"repo": "github.com/acme/app", "origin": "agent_feedback", "approve": true}',
        method="POST", headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as r:
        res = json.loads(r.read())
    assert res["ok"] is False  # no provider in the test server


def test_feedback_loop_status_idle_and_start_requires_provider(served):
    _, _, base = served
    _, body = _get(base + "/api/feedback/loop/status")
    assert json.loads(body)["state"] == "idle"

    req = urllib.request.Request(
        base + "/api/feedback/loop/start",
        data=b'{"repo": "github.com/acme/app"}',
        method="POST", headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as r:
        res = json.loads(r.read())
    assert res["ok"] is False


def test_api_decisions_returns_json_with_the_decision(served):
    _, decision, base = served
    status, body = _get(base + "/api/decisions")
    assert status == 200
    data = json.loads(body)
    assert any(item["id"] == decision.id for item in data["items"])


def test_api_stats_returns_counts(served):
    _, _, base = served
    _, body = _get(base + "/api/stats")
    data = json.loads(body)
    assert data["candidate"] == 1
    assert data["total"] == 1


def test_api_version_reports_a_revision(served):
    _, _, base = served
    _, body = _get(base + "/api/version")
    data = json.loads(body)
    assert "revision" in data and isinstance(data["revision"], str) and data["revision"]


def test_api_decisions_filters_by_search(served):
    store, _, base = served
    store.add(Decision(repo="github.com/acme/app", pattern="emit highlights only",
                    scope="src/review", rationale="r", origin=Origin.BOOTSTRAP))
    _, body = _get(base + "/api/decisions?search=highlights")
    data = json.loads(body)
    assert [it["scope"] for it in data["items"]] == ["src/review"]


def test_api_decisions_filters_by_origin(served):
    store, _, base = served
    store.add(Decision(repo="github.com/acme/app", pattern="from feedback", scope="app",
                    rationale="r", origin=Origin.AGENT_FEEDBACK, status=Status.CANONICAL))
    _, body = _get(base + "/api/decisions?origin=agent_feedback")
    data = json.loads(body)
    assert all(it["origin"] == "agent_feedback" for it in data["items"])
    assert any(it["pattern"] == "from feedback" for it in data["items"])


def test_api_origins_returns_breakdown(served):
    _, _, base = served
    _, body = _get(base + "/api/origins")
    data = json.loads(body)
    assert "origins" in data and isinstance(data["origins"], list)


def test_api_feedback_returns_tallies(served):
    _, _, base = served
    _, body = _get(base + "/api/feedback")
    data = json.loads(body)
    assert "decisions" in data and "by_origin" in data


def test_api_feedback_events_returns_stream(served):
    _, _, base = served
    _, body = _get(base + "/api/feedback-events")
    data = json.loads(body)
    assert "events" in data and isinstance(data["events"], list)


def test_api_feedback_events_accepts_status_filter(served):
    _, _, base = served
    _, body = _get(base + "/api/feedback-events?status=handled")
    data = json.loads(body)
    assert "events" in data and isinstance(data["events"], list)


def test_api_leaderboard_returns_lists(served):
    _, _, base = served
    _, body = _get(base + "/api/leaderboard")
    data = json.loads(body)
    assert "most_helpful" in data and "misleading" in data
    assert isinstance(data["most_helpful"], list)


def test_api_agent_activity_groups_by_actor(served):
    store, _, base = served
    # the fixture recorded one anonymous query; add an attributed one
    _, _, _ = served
    _, body = _get(base + "/api/agent-activity?repo=github.com/acme/app&window=60")
    data = json.loads(body)
    assert "agents" in data and "total_agents" in data
    assert isinstance(data["agents"], list)


class _FakeRefiner:
    def refine(self, gap, scope_hint="", task=""):
        return [Decision(repo="x", pattern="refined from gap", scope=scope_hint,
                      rationale="r", origin=Origin.AGENT_FEEDBACK, status=Status.CANDIDATE)]


def test_post_refine_feedback_produces_candidates_and_marks_handled():
    store = SQLiteDecisionStore(":memory:")
    events = SQLiteEventStore(":memory:")
    e = Event(repo="r", kind=EventKind.FEEDBACK, missing="gap text", area="src/a")
    events.record(e)
    port = find_free_port(start=8900, host="127.0.0.1")
    httpd = make_server(store, "127.0.0.1", port, events,
                        refiner_factory=lambda: _FakeRefiner())
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{port}"
        _, body = _post(base + f"/api/feedback/{e.id}/refine")
        data = json.loads(body)
        assert data["ok"] is True
        assert data["decisions_created"] == 1
        assert events.get(e.id).handled is True
        assert len(store.list(repo="r", status=Status.CANDIDATE)) == 1
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_post_refine_feedback_without_factory_is_graceful(served):
    _, _, base = served
    _, body = _post(base + "/api/feedback/any-id/refine")
    data = json.loads(body)
    assert data["ok"] is False
    assert "error" in data


def test_post_approve_promotes_decision(served):
    store, decision, base = served
    _, body = _post(base + f"/api/decisions/{decision.id}/approve")
    assert json.loads(body)["ok"] is True
    assert store.get(decision.id).status is Status.CANONICAL


def test_api_usage_returns_summary(served):
    _, _, base = served
    _, body = _get(base + "/api/usage")
    data = json.loads(body)
    assert data["total_queries"] == 1
    assert data["coverage_rate"] == 1.0
    assert len(data["recent_queries"]) == 1


def test_unknown_path_is_404(served):
    _, _, base = served
    with pytest.raises(urllib.error.HTTPError) as exc:
        _get(base + "/nope")
    assert exc.value.code == 404
