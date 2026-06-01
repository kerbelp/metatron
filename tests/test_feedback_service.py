"""Phase 2 of the feedback loop: service logic.

submit_feedback resolves per-prior ratings by *index* against the stored QUERY
event, records a FEEDBACK event, and routes "what was missing" into the candidate
queue (origin=agent_feedback, never canonical). format_priors surfaces a query
token + build revision + 1-based indices so the agent can reference results.
"""

from metatron.events import Event, EventKind
from metatron.mcp_server.service import format_priors, submit_feedback
from metatron.models import Origin, Prior, Status
from metatron.storage.sqlite import SQLiteEventStore, SQLitePriorStore

REPO = "github.com/acme/app"


def _canonical(pattern, scope="app") -> Prior:
    return Prior(repo=REPO, pattern=pattern, scope=scope, rationale="r",
                 origin=Origin.BOOTSTRAP, status=Status.CANONICAL)


def _served_query(events, prior_ids) -> str:
    ev = Event(repo=REPO, kind=EventKind.QUERY, area="a", task="t", prior_ids=prior_ids)
    events.record(ev)
    return ev.id


# --- format_priors: query token, revision, indices ---

def test_format_priors_includes_query_token_revision_and_indices():
    out = format_priors(
        [_canonical("first rule"), _canonical("second rule")],
        query_id="q-123",
        version="abc1234",
    )
    assert "q-123" in out
    assert "abc1234" in out
    assert "[1]" in out and "[2]" in out


def test_format_priors_without_metadata_still_works():
    # back-compat: callers that don't pass query_id/version still get readable output
    out = format_priors([_canonical("a rule")])
    assert "a rule" in out


# --- submit_feedback: ratings by index ---

def test_feedback_maps_indices_to_prior_ids_and_records_event():
    store, events = SQLitePriorStore(":memory:"), SQLiteEventStore(":memory:")
    qid = _served_query(events, ["p1", "p2", "p3"])

    submit_feedback(store, events, repo=REPO, query_id=qid, helpful=[1, 3], unhelpful=[2])

    fb = [e for e in events.list_events() if e.kind is EventKind.FEEDBACK][0]
    assert fb.query_ref == qid
    assert fb.helpful_prior_ids == ["p1", "p3"]
    assert fb.unhelpful_prior_ids == ["p2"]


def test_feedback_ignores_out_of_range_indices():
    store, events = SQLitePriorStore(":memory:"), SQLiteEventStore(":memory:")
    qid = _served_query(events, ["p1", "p2"])

    submit_feedback(store, events, repo=REPO, query_id=qid, helpful=[1, 99])

    fb = [e for e in events.list_events() if e.kind is EventKind.FEEDBACK][0]
    assert fb.helpful_prior_ids == ["p1"]


# --- submit_feedback: what_was_missing -> candidate ---

def test_what_was_missing_creates_one_candidate_never_canonical():
    store, events = SQLitePriorStore(":memory:"), SQLiteEventStore(":memory:")
    qid = _served_query(events, ["p1"])

    submit_feedback(
        store, events, repo=REPO, query_id=qid,
        what_was_missing="the credit path must mirror the order_created webhook",
        missing_scope="src/routes/api/order_created",
    )

    candidates = store.list(repo=REPO)
    assert len(candidates) == 1
    c = candidates[0]
    assert c.status is Status.CANDIDATE          # never canonical
    assert c.origin is Origin.AGENT_FEEDBACK
    assert "order_created webhook" in c.pattern
    assert c.scope == "src/routes/api/order_created"


def test_gap_report_works_without_a_query_id():
    store, events = SQLitePriorStore(":memory:"), SQLiteEventStore(":memory:")

    submit_feedback(
        store, events, repo=REPO,
        what_was_missing="ledger consume must be atomic", missing_scope="src/db",
    )

    assert len(store.list(repo=REPO)) == 1
    # a FEEDBACK event is still recorded
    assert any(e.kind is EventKind.FEEDBACK for e in events.list_events())


def test_ratings_only_feedback_creates_no_candidate():
    store, events = SQLitePriorStore(":memory:"), SQLiteEventStore(":memory:")
    qid = _served_query(events, ["p1"])

    submit_feedback(store, events, repo=REPO, query_id=qid, helpful=[1])

    assert store.list(repo=REPO) == []
