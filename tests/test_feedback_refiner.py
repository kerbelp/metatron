"""The Opus feedback refiner: reshape raw gap reports into structured candidates.

LLM-assisted but human-gated — every prior it produces is a candidate of
agent_feedback origin, never canonical. Processed feedback is marked handled so a
re-run is idempotent.
"""

import json

import pytest

from metatron.events import Event, EventKind
from metatron.extraction.feedback_refiner import FeedbackRefiner, RefineError
from metatron.extraction.provider import LLMProvider
from metatron.models import Origin, Prior, Status
from metatron.pipeline import refine_feedback
from metatron.storage.sqlite import SQLiteEventStore, SQLitePriorStore

REPO = "github.com/acme/app"


class StaticProvider(LLMProvider):
    def __init__(self, response: str) -> None:
        self.response = response

    def complete(self, prompt: str) -> str:
        return self.response


# --- FeedbackRefiner ---

def test_refiner_splits_a_gap_into_multiple_structured_candidates():
    resp = json.dumps([
        {"pattern": "Mirror the order_created publish chain", "scope": "src/x",
         "rationale": "keeps publish paths consistent", "confidence": "high"},
        {"pattern": "Guard the non-idempotent insert with the localStorage flag",
         "scope": "src/x", "rationale": "avoids UNIQUE errors on retry", "confidence": "medium"},
    ])
    priors = FeedbackRefiner(StaticProvider(resp)).refine("big gap text", scope_hint="src/x")
    assert len(priors) == 2
    assert all(p.origin is Origin.AGENT_FEEDBACK and p.status is Status.CANDIDATE for p in priors)
    assert priors[0].pattern.startswith("Mirror")


def test_refiner_defaults_scope_to_hint_and_skips_empty_patterns():
    resp = json.dumps([{"scope": "", "rationale": "r"}, {"pattern": "Real rule", "rationale": "r"}])
    priors = FeedbackRefiner(StaticProvider(resp)).refine("g", scope_hint="src/db")
    assert [p.pattern for p in priors] == ["Real rule"]
    assert priors[0].scope == "src/db"


def test_refiner_handles_fenced_json():
    resp = "```json\n" + json.dumps([{"pattern": "X", "rationale": "r"}]) + "\n```"
    assert FeedbackRefiner(StaticProvider(resp)).refine("g")[0].pattern == "X"


def test_refiner_raises_on_malformed_json():
    with pytest.raises(RefineError):
        FeedbackRefiner(StaticProvider("not json")).refine("g")


# --- refine_feedback orchestration ---

class FakeRefiner:
    def __init__(self, n: int = 2) -> None:
        self.n = n

    def refine(self, gap: str, scope_hint: str = "", task: str = "") -> list[Prior]:
        return [
            Prior(repo="placeholder", pattern=f"p{i}:{gap[:6]}", scope=scope_hint,
                  rationale="r", origin=Origin.AGENT_FEEDBACK)
            for i in range(self.n)
        ]


def test_refine_feedback_creates_candidates_marks_handled_and_is_idempotent():
    s, ev = SQLitePriorStore(":memory:"), SQLiteEventStore(":memory:")
    ev.record(Event(repo=REPO, kind=EventKind.FEEDBACK, missing="gap one", area="src/a"))
    ev.record(Event(repo=REPO, kind=EventKind.FEEDBACK, missing="gap two", area="src/b"))

    res = refine_feedback(s, ev, FakeRefiner(2), repo=REPO)
    assert (res.events_processed, res.priors_created) == (2, 4)
    created = s.list(repo=REPO)
    assert len(created) == 4
    assert all(p.repo == REPO for p in created)  # stamped from the event, not the refiner
    assert ev.unhandled_feedback(repo=REPO) == []

    again = refine_feedback(s, ev, FakeRefiner(2), repo=REPO)
    assert (again.events_processed, again.priors_created) == (0, 0)


def test_ratings_only_feedback_is_marked_handled_without_candidates():
    s, ev = SQLitePriorStore(":memory:"), SQLiteEventStore(":memory:")
    ev.record(Event(repo=REPO, kind=EventKind.FEEDBACK, missing="", helpful_prior_ids=["x"]))

    res = refine_feedback(s, ev, FakeRefiner(2), repo=REPO)
    assert res.priors_created == 0
    assert ev.unhandled_feedback(repo=REPO) == []  # not reprocessed forever
