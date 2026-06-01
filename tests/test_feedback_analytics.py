"""Phase 4 backend: origin filter + ingest-vs-feedback analytics.

Answers "are feedback-born priors better than ingest-born?" via curation
accept-rate and helpful-rate grouped by origin. Advisory only — reads counts and
feedback events, never mutates priors.
"""

from metatron.events import Event, EventKind
from metatron.models import Origin, Prior, Status
from metatron.storage.sqlite import SQLiteEventStore, SQLitePriorStore
from metatron.webui.api import feedback_analytics, origin_breakdown

REPO = "github.com/acme/app"


def _p(origin, status=Status.CANDIDATE, pattern="p") -> Prior:
    return Prior(repo=REPO, pattern=pattern, scope="app", rationale="r",
                 origin=origin, status=status)


def test_store_filters_by_origin():
    s = SQLitePriorStore(":memory:")
    s.add(_p(Origin.BOOTSTRAP))
    s.add(_p(Origin.AGENT_FEEDBACK))
    assert {p.origin for p in s.list(origin=Origin.AGENT_FEEDBACK)} == {Origin.AGENT_FEEDBACK}
    assert s.count(origin=Origin.BOOTSTRAP) == 1


def test_origin_breakdown_reports_accept_rate_per_origin():
    s = SQLitePriorStore(":memory:")
    s.add(_p(Origin.BOOTSTRAP, Status.CANONICAL))
    s.add(_p(Origin.BOOTSTRAP, Status.REJECTED))            # ingest: 1/2 accepted
    s.add(_p(Origin.AGENT_FEEDBACK, Status.CANONICAL))
    s.add(_p(Origin.AGENT_FEEDBACK, Status.CANONICAL))      # feedback: 2/2 accepted
    out = {o["origin"]: o for o in origin_breakdown(s)["origins"]}
    assert out["bootstrap"]["accept_rate"] == 0.5
    assert out["agent_feedback"]["accept_rate"] == 1.0
    assert out["bootstrap"]["total"] == 2


def test_origin_breakdown_accept_rate_is_none_without_decisions():
    s = SQLitePriorStore(":memory:")
    s.add(_p(Origin.AGENT_FEEDBACK, Status.CANDIDATE))  # not yet curated
    out = {o["origin"]: o for o in origin_breakdown(s)["origins"]}
    assert out["agent_feedback"]["accept_rate"] is None


def test_feedback_analytics_tallies_helpful_and_noise_by_origin():
    s, ev = SQLitePriorStore(":memory:"), SQLiteEventStore(":memory:")
    boot = _p(Origin.BOOTSTRAP, Status.CANONICAL, pattern="ingest rule")
    fb = _p(Origin.AGENT_FEEDBACK, Status.CANONICAL, pattern="feedback rule")
    s.add(boot)
    s.add(fb)
    ev.record(Event(repo=REPO, kind=EventKind.FEEDBACK,
                    helpful_prior_ids=[fb.id], unhelpful_prior_ids=[boot.id]))
    ev.record(Event(repo=REPO, kind=EventKind.FEEDBACK, helpful_prior_ids=[fb.id]))

    out = feedback_analytics(ev, s)
    by = {o["origin"]: o for o in out["by_origin"]}
    assert by["agent_feedback"]["helpful"] == 2
    assert by["agent_feedback"]["noise"] == 0
    assert by["bootstrap"]["noise"] == 1
    per = {p["id"]: p for p in out["priors"]}
    assert per[fb.id]["helpful"] == 2 and per[fb.id]["pattern"] == "feedback rule"
