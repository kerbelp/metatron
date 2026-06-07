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


def test_anonymous_events_group_under_a_single_bucket():
    store = SQLiteDecisionStore(":memory:")
    events = SQLiteEventStore(":memory:")
    events.record(Event(repo=REPO, kind=EventKind.QUERY, area="x", timestamp=_now()))
    result = agent_activity(events, store, repo=REPO, window_mins=30)
    assert result["total_agents"] == 1
    assert result["agents"][0]["name"]  # has a display fallback, not empty
