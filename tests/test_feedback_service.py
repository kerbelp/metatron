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


# --- submit_feedback: capture-only (the refiner creates candidates later) ---

def test_what_was_missing_is_captured_without_creating_a_candidate():
    store, events = SQLitePriorStore(":memory:"), SQLiteEventStore(":memory:")
    qid = _served_query(events, ["p1"])

    submit_feedback(
        store, events, repo=REPO, query_id=qid,
        what_was_missing="the credit path must mirror the order_created webhook",
        missing_scope="src/routes/api/order_created",
    )

    # No candidate is created at capture time — the Opus refiner does that later.
    assert store.list(repo=REPO) == []
    fb = [e for e in events.list_events() if e.kind is EventKind.FEEDBACK][0]
    assert "order_created webhook" in fb.missing
    assert fb.area == "src/routes/api/order_created"  # scope hint preserved
    assert fb.handled is False


def test_gap_report_works_without_a_query_id():
    store, events = SQLitePriorStore(":memory:"), SQLiteEventStore(":memory:")

    submit_feedback(
        store, events, repo=REPO,
        what_was_missing="ledger consume must be atomic", missing_scope="src/db",
    )

    assert store.list(repo=REPO) == []
    assert any(e.kind is EventKind.FEEDBACK for e in events.list_events())


def test_ratings_only_feedback_creates_no_candidate():
    store, events = SQLitePriorStore(":memory:"), SQLiteEventStore(":memory:")
    qid = _served_query(events, ["p1"])

    submit_feedback(store, events, repo=REPO, query_id=qid, helpful=[1])

    assert store.list(repo=REPO) == []


# --- submit_feedback: graded 1-10 ratings by index ---

def test_graded_ratings_map_indices_to_prior_ids():
    store, events = SQLitePriorStore(":memory:"), SQLiteEventStore(":memory:")
    qid = _served_query(events, ["p1", "p2", "p3"])

    # string keys (how a model emits JSON object keys) and ints both resolve
    submit_feedback(store, events, repo=REPO, query_id=qid,
                    ratings={"1": 9, "2": 2, 3: 7})

    fb = [e for e in events.list_events() if e.kind is EventKind.FEEDBACK][0]
    assert fb.ratings == {"p1": 9, "p2": 2, "p3": 7}


def test_graded_ratings_drop_out_of_range_index_and_out_of_band_score():
    store, events = SQLitePriorStore(":memory:"), SQLiteEventStore(":memory:")
    qid = _served_query(events, ["p1", "p2"])

    submit_feedback(store, events, repo=REPO, query_id=qid,
                    ratings={"1": 8, "99": 5, "2": 0, "x": 4})

    fb = [e for e in events.list_events() if e.kind is EventKind.FEEDBACK][0]
    assert fb.ratings == {"p1": 8}  # bad index/score/key all dropped


def test_binary_helpful_unhelpful_derived_from_ratings_when_omitted():
    store, events = SQLitePriorStore(":memory:"), SQLiteEventStore(":memory:")
    qid = _served_query(events, ["p1", "p2", "p3"])

    submit_feedback(store, events, repo=REPO, query_id=qid,
                    ratings={"1": 9, "2": 5, "3": 2})

    fb = [e for e in events.list_events() if e.kind is EventKind.FEEDBACK][0]
    assert fb.helpful_prior_ids == ["p1"]      # >=7
    assert fb.unhelpful_prior_ids == ["p3"]    # <=4; the mid score (5) is neither


def test_explicit_binary_lists_take_precedence_over_derivation():
    store, events = SQLitePriorStore(":memory:"), SQLiteEventStore(":memory:")
    qid = _served_query(events, ["p1", "p2"])

    submit_feedback(store, events, repo=REPO, query_id=qid,
                    ratings={"1": 9, "2": 2}, helpful=[2], unhelpful=[1])

    fb = [e for e in events.list_events() if e.kind is EventKind.FEEDBACK][0]
    assert fb.ratings == {"p1": 9, "p2": 2}    # graded scores still recorded
    assert fb.helpful_prior_ids == ["p2"]      # but explicit lists win
    assert fb.unhelpful_prior_ids == ["p1"]
