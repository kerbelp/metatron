"""Tests for the MCP service logic (retrieval + submission), server-independent."""

from metatron.mcp_server.service import (
    format_priors,
    get_priors_for_context,
    submit_candidate_learning,
)
from metatron.models import Confidence, Origin, Prior, Status
from metatron.storage.sqlite import SQLitePriorStore


def _canonical(**kw) -> Prior:
    kw.setdefault("origin", Origin.BOOTSTRAP)
    return Prior(status=Status.CANONICAL, **kw)


def _store(*priors) -> SQLitePriorStore:
    s = SQLitePriorStore(":memory:")
    for p in priors:
        s.add(p)
    return s


def test_only_canonical_priors_are_served():
    store = _store(
        _canonical(pattern="canon", scope="app", rationale="r"),
        Prior(pattern="cand", scope="app", rationale="r", origin=Origin.BOOTSTRAP),
    )
    results = get_priors_for_context(store, "app", "anything")
    assert [p.pattern for p in results] == ["canon"]


def test_out_of_scope_priors_are_excluded():
    store = _store(
        _canonical(pattern="storage rule", scope="app/storage", rationale="r"),
        _canonical(pattern="ui rule", scope="app/ui", rationale="r"),
    )
    results = get_priors_for_context(store, "app/storage/db.py", "task")
    assert [p.pattern for p in results] == ["storage rule"]


def test_global_scope_priors_always_match():
    store = _store(_canonical(pattern="global rule", scope="", rationale="r"))
    results = get_priors_for_context(store, "anywhere/at/all.py", "task")
    assert [p.pattern for p in results] == ["global rule"]


def test_keyword_overlap_with_task_ranks_higher():
    store = _store(
        _canonical(pattern="use retries for network calls", scope="app", rationale="flaky"),
        _canonical(pattern="prefer dataclasses for config", scope="app", rationale="clarity"),
    )
    results = get_priors_for_context(store, "app", "add retries to the network client")
    assert results[0].pattern == "use retries for network calls"


def test_submit_candidate_learning_stores_uncurated_agent_prior():
    store = SQLitePriorStore(":memory:")
    prior = submit_candidate_learning(
        store,
        pattern="always log request ids",
        scope="app/api",
        rationale="traceability",
        confidence="high",
    )
    assert prior.id
    assert prior.status is Status.CANDIDATE
    assert prior.origin is Origin.AGENT_SUBMITTED
    assert prior.confidence is Confidence.HIGH
    # persisted
    assert store.get(prior.id) is not None


def test_submit_defaults_bad_confidence_to_medium():
    store = SQLitePriorStore(":memory:")
    prior = submit_candidate_learning(
        store, pattern="p", scope="s", rationale="r", confidence="bogus"
    )
    assert prior.confidence is Confidence.MEDIUM


def test_format_priors_is_compact_and_names_each_pattern():
    text = format_priors(
        [_canonical(pattern="rule one", scope="app", rationale="because")]
    )
    assert "rule one" in text
    assert "because" in text


def test_format_priors_handles_no_matches():
    assert "no" in format_priors([]).lower()
