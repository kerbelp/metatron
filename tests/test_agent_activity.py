"""Agent activity = recent events grouped by the employee (actor) who produced them."""

from datetime import datetime, timedelta, timezone

from metatron.events import Event, EventKind
from metatron.models import Origin, Decision, Status
from metatron.storage.sqlite import SQLiteEventStore, SQLiteDecisionStore
from metatron.webui.api import agent_activity

REPO = "acme/app"


def _now():
    return datetime.now(timezone.utc)


def test_groups_recent_events_by_actor_within_window():
    store = SQLiteDecisionStore(":memory:")
    decision = Decision(repo=REPO, pattern="use zod", scope="src/api", rationale="r",
                  origin=Origin.BOOTSTRAP, status=Status.CANONICAL)
    store.add(decision)
    events = SQLiteEventStore(":memory:")
    # Nova: two queries + one feedback, all recent
    events.record(Event(repo=REPO, kind=EventKind.QUERY, area="src/api", task="add webhook",
                        result_count=1, decision_ids=[decision.id],
                        actor_id="n1", actor_name="Nova", timestamp=_now()))
    events.record(Event(repo=REPO, kind=EventKind.QUERY, area="src/api", result_count=0,
                        actor_id="n1", actor_name="Nova", timestamp=_now()))
    events.record(Event(repo=REPO, kind=EventKind.FEEDBACK, actor_id="n1", actor_name="Nova",
                        timestamp=_now()))
    # Andromeda: one recent query
    events.record(Event(repo=REPO, kind=EventKind.QUERY, area="src/db", task="pagination",
                        result_count=1, decision_ids=[decision.id],
                        actor_id="a1", actor_name="Andromeda", timestamp=_now()))
    # An old event, outside the window — excluded
    events.record(Event(repo=REPO, kind=EventKind.QUERY, area="old", result_count=0,
                        actor_id="z9", actor_name="Ghost",
                        timestamp=_now() - timedelta(minutes=90)))

    result = agent_activity(events, store, repo=REPO, window_mins=30)

    assert result["total_agents"] == 2
    assert {a["name"] for a in result["agents"]} == {"Nova", "Andromeda"}
    nova = next(a for a in result["agents"] if a["name"] == "Nova")
    assert nova["queries"] == 2
    assert nova["feedback_sent"] == 1
    assert nova["decisions_received"] == 1  # summed over the actor's queries
    assert nova["status"] == "feedback"  # most recent event was feedback
    andromeda = next(a for a in result["agents"] if a["name"] == "Andromeda")
    assert andromeda["status"] == "serving"  # most recent event was a query
    assert result["total_feedback"] == 1
    assert "Ghost" not in {a["name"] for a in result["agents"]}


def test_reports_last_active_timestamp_of_most_recent_event():
    # The UI renders "last active <relative time>" from this ISO timestamp.
    store = SQLiteDecisionStore(":memory:")
    events = SQLiteEventStore(":memory:")
    older = _now() - timedelta(minutes=5)
    newest = _now() - timedelta(minutes=1)
    events.record(Event(repo=REPO, kind=EventKind.QUERY, area="a", actor_id="n1",
                        actor_name="Nova", timestamp=older))
    events.record(Event(repo=REPO, kind=EventKind.QUERY, area="b", actor_id="n1",
                        actor_name="Nova", timestamp=newest))

    result = agent_activity(events, store, repo=REPO, window_mins=30)

    assert result["agents"][0]["last_active"] == newest.isoformat()


def test_agent_entry_includes_received_decisions_and_feedback_detail():
    # Powers the drill-down drawers: clicking an agent's stats shows the actual
    # decisions it received and the feedback it sent.
    store = SQLiteDecisionStore(":memory:")
    d1 = Decision(repo=REPO, pattern="use zod", scope="src/api", rationale="r",
                  origin=Origin.BOOTSTRAP, status=Status.CANONICAL)
    d2 = Decision(repo=REPO, pattern="pin deps", scope="src", rationale="r2",
                  origin=Origin.BOOTSTRAP, status=Status.CANONICAL)
    store.add(d1)
    store.add(d2)
    events = SQLiteEventStore(":memory:")
    # Two queries (d1+d2, then d1 again) prove received is deduped across queries.
    events.record(Event(repo=REPO, kind=EventKind.QUERY, area="src/api", task="add webhook",
                        result_count=2, decision_ids=[d1.id, d2.id],
                        actor_id="n1", actor_name="Nova", timestamp=_now()))
    events.record(Event(repo=REPO, kind=EventKind.QUERY, area="src/api", task="retry logic",
                        result_count=1, decision_ids=[d1.id],
                        actor_id="n1", actor_name="Nova", timestamp=_now()))
    events.record(Event(repo=REPO, kind=EventKind.FEEDBACK, area="src/api", task="add webhook",
                        missing="No guidance on webhook retries", ratings={d1.id: 8},
                        decision_ids=[d1.id], actor_id="n1", actor_name="Nova", timestamp=_now()))

    result = agent_activity(events, store, repo=REPO, window_mins=30)
    nova = next(a for a in result["agents"] if a["name"] == "Nova")

    received_ids = [r["id"] for r in nova["received"]]
    assert received_ids == [d1.id, d2.id]  # deduped, in first-seen order
    assert nova["received"][0]["pattern"] == "use zod"
    assert nova["received"][0]["status"] == "canonical"

    assert len(nova["feedback"]) == 1
    fb = nova["feedback"][0]
    assert fb["missing"] == "No guidance on webhook retries"
    assert fb["ratings"] == {d1.id: 8}
    assert [d["id"] for d in fb["decisions"]] == [d1.id]


def test_anonymous_events_group_under_a_single_bucket():
    store = SQLiteDecisionStore(":memory:")
    events = SQLiteEventStore(":memory:")
    events.record(Event(repo=REPO, kind=EventKind.QUERY, area="x", timestamp=_now()))
    result = agent_activity(events, store, repo=REPO, window_mins=30)
    assert result["total_agents"] == 1
    assert result["agents"][0]["name"]  # has a display fallback, not empty
