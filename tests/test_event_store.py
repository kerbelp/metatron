"""Tests for usage-event recording and retrieval."""

from datetime import datetime, timezone

import pytest

from metatron.events import Event, EventKind
from metatron.storage.base import EventStore
from metatron.storage.sqlite import SQLiteEventStore


@pytest.fixture
def events() -> SQLiteEventStore:
    s = SQLiteEventStore(":memory:")
    yield s
    s.close()


def _query(day: int, area="src/components/Home", count=2, ids=None, repo="github.com/acme/app") -> Event:
    return Event(
        repo=repo,
        kind=EventKind.QUERY,
        area=area,
        task="add a section",
        result_count=count,
        prior_ids=ids or ["a", "b"],
        timestamp=datetime(2024, 1, day, tzinfo=timezone.utc),
    )


def test_sqlite_event_store_is_an_event_store(events):
    assert isinstance(events, EventStore)


def test_event_store_is_abstract():
    with pytest.raises(TypeError):
        EventStore()  # type: ignore[abstract]


def test_record_then_round_trips(events):
    event = _query(1)
    events.record(event)

    loaded = events.list_events()
    assert loaded == [event]


def test_list_events_newest_first_with_pagination(events):
    older = _query(1, area="a")
    newer = _query(5, area="b")
    events.record(older)
    events.record(newer)

    assert [e.area for e in events.list_events()] == ["b", "a"]
    assert [e.area for e in events.list_events(limit=1)] == ["b"]
    assert [e.area for e in events.list_events(limit=1, offset=1)] == ["a"]


def test_count_events(events):
    events.record(_query(1))
    events.record(_query(2))
    assert events.count_events() == 2
