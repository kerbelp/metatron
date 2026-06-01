"""Phase 1 of the feedback loop: data-model + storage groundwork.

Build-version provenance (Event.version, Prior.created_version), the feedback
event shape, and EventStore.get for index resolution. No behavior yet — just the
storage substrate, all additive and migration-safe.
"""

from metatron.events import Event, EventKind
from metatron.models import Origin, Prior, Status
from metatron.storage.sqlite import SQLiteEventStore, SQLitePriorStore


def _prior(**kw) -> Prior:
    kw.setdefault("repo", "github.com/acme/app")
    kw.setdefault("pattern", "p")
    kw.setdefault("scope", "app")
    kw.setdefault("rationale", "r")
    kw.setdefault("origin", Origin.BOOTSTRAP)
    return Prior(**kw)


def test_agent_feedback_origin_exists():
    assert Origin.AGENT_FEEDBACK.value == "agent_feedback"


def test_feedback_event_kind_exists():
    assert EventKind.FEEDBACK.value == "feedback"


def test_new_prior_is_stamped_with_a_build_version():
    # created_version is auto-populated from the running build, non-empty.
    assert _prior().created_version


def test_new_event_is_stamped_with_a_build_version():
    assert Event(repo="r", kind=EventKind.QUERY).version


def test_prior_created_version_survives_a_store_round_trip():
    store = SQLitePriorStore(":memory:")
    p = _prior(created_version="abc1234")
    store.add(p)
    assert store.get(p.id).created_version == "abc1234"


def test_feedback_event_round_trips_with_ratings_and_missing_text():
    store = SQLiteEventStore(":memory:")
    ev = Event(
        repo="github.com/acme/app",
        kind=EventKind.FEEDBACK,
        query_ref="query-123",
        helpful_prior_ids=["a", "b"],
        unhelpful_prior_ids=["c"],
        missing="credit path must mirror the order_created webhook",
        version="abc1234",
    )
    store.record(ev)
    got = store.list_events()[0]
    assert got.kind is EventKind.FEEDBACK
    assert got.query_ref == "query-123"
    assert got.helpful_prior_ids == ["a", "b"]
    assert got.unhelpful_prior_ids == ["c"]
    assert got.missing.startswith("credit path")
    assert got.version == "abc1234"


def test_event_store_get_returns_event_by_id_for_index_resolution():
    store = SQLiteEventStore(":memory:")
    ev = Event(repo="r", kind=EventKind.QUERY, prior_ids=["p1", "p2", "p3"])
    store.record(ev)
    fetched = store.get(ev.id)
    assert fetched is not None
    assert fetched.prior_ids == ["p1", "p2", "p3"]
    assert store.get("no-such-id") is None


def test_unhandled_feedback_excludes_handled_and_non_feedback():
    store = SQLiteEventStore(":memory:")
    fb = Event(repo="r", kind=EventKind.FEEDBACK, missing="gap a")
    other = Event(repo="r", kind=EventKind.FEEDBACK, missing="gap b")
    store.record(Event(repo="r", kind=EventKind.QUERY))  # not feedback
    store.record(fb)
    store.record(other)

    assert {e.id for e in store.unhandled_feedback()} == {fb.id, other.id}

    store.mark_handled(fb.id, produced_ids=["cand1", "cand2"])
    remaining = store.unhandled_feedback()
    assert [e.id for e in remaining] == [other.id]
    # provenance: the handled event records what it produced
    assert store.get(fb.id).handled is True
    assert store.get(fb.id).prior_ids == ["cand1", "cand2"]
