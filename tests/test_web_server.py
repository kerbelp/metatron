"""Tests for the web server: free-port selection and real HTTP round-trips."""

import json
import socket
import threading
import urllib.request

import pytest

from metatron.events import Event, EventKind
from metatron.models import Origin, Prior, Status
from metatron.storage.sqlite import SQLiteEventStore, SQLitePriorStore
from metatron.webui.server import find_free_port, make_server


def _get(url: str):
    with urllib.request.urlopen(url) as r:
        return r.status, r.read()


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
    store = SQLitePriorStore(":memory:")
    prior = Prior(repo="github.com/acme/app", pattern="serve me", scope="app", rationale="r", origin=Origin.BOOTSTRAP)
    store.add(prior)
    events = SQLiteEventStore(":memory:")
    events.record(Event(repo="github.com/acme/app", kind=EventKind.QUERY, area="app", result_count=1))
    port = find_free_port(start=8800, host="127.0.0.1")
    httpd = make_server(store, "127.0.0.1", port, events)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield store, prior, f"http://127.0.0.1:{port}"
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_root_serves_html(served):
    _, _, base = served
    status, body = _get(base + "/")
    assert status == 200
    assert b"<!doctype html>" in body.lower() or b"<html" in body.lower()


def test_api_priors_returns_json_with_the_prior(served):
    _, prior, base = served
    status, body = _get(base + "/api/priors")
    assert status == 200
    data = json.loads(body)
    assert any(item["id"] == prior.id for item in data["items"])


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


def test_footer_markup_present_in_html(served):
    _, _, base = served
    _, body = _get(base + "/")
    assert b'id="version"' in body


def test_quality_analytics_markup_present_in_html(served):
    _, _, base = served
    _, body = _get(base + "/")
    assert b'id="origin-breakdown"' in body
    assert b'id="feedback-summary"' in body


def test_origin_filter_dropdown_present_in_html(served):
    _, _, base = served
    _, body = _get(base + "/")
    assert b'id="origin-filter"' in body


def test_api_priors_filters_by_origin(served):
    store, _, base = served
    store.add(Prior(repo="github.com/acme/app", pattern="from feedback", scope="app",
                    rationale="r", origin=Origin.AGENT_FEEDBACK, status=Status.CANONICAL))
    _, body = _get(base + "/api/priors?origin=agent_feedback")
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
    assert "priors" in data and "by_origin" in data


def test_api_feedback_events_returns_stream(served):
    _, _, base = served
    _, body = _get(base + "/api/feedback-events")
    data = json.loads(body)
    assert "events" in data and isinstance(data["events"], list)


def test_nav_has_usage_quality_feedback_tabs(served):
    _, _, base = served
    _, body = _get(base + "/")
    for view in (b'data-view="usage"', b'data-view="quality"', b'data-view="feedback"'):
        assert view in body


def test_post_approve_promotes_prior(served):
    store, prior, base = served
    _, body = _post(base + f"/api/priors/{prior.id}/approve")
    assert json.loads(body)["ok"] is True
    assert store.get(prior.id).status is Status.CANONICAL


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
