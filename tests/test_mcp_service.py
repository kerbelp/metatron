"""Tests for the MCP service logic (retrieval + submission), server-independent."""

from metatron.mcp_server.service import (
    format_priors,
    get_priors_for_context,
    submit_candidate_learning,
)
from metatron.models import Confidence, Origin, Prior, Status
from metatron.storage.sqlite import SQLitePriorStore

REPO = "github.com/acme/app"


def _canonical(**kw) -> Prior:
    kw.setdefault("origin", Origin.BOOTSTRAP)
    kw.setdefault("repo", REPO)
    return Prior(status=Status.CANONICAL, **kw)


def _store(*priors) -> SQLitePriorStore:
    s = SQLitePriorStore(":memory:")
    for p in priors:
        s.add(p)
    return s


def test_only_canonical_priors_are_served():
    store = _store(
        _canonical(pattern="canon", scope="app", rationale="r"),
        Prior(repo=REPO, pattern="cand", scope="app", rationale="r", origin=Origin.BOOTSTRAP),
    )
    results = get_priors_for_context(store, REPO, "app", "anything")
    assert [p.pattern for p in results] == ["canon"]


def test_only_the_requested_repos_priors_are_served():
    store = _store(
        _canonical(pattern="mine", scope="app", rationale="r", repo=REPO),
        _canonical(pattern="theirs", scope="app", rationale="r", repo="github.com/other/x"),
    )
    results = get_priors_for_context(store, REPO, "app", "anything")
    assert [p.pattern for p in results] == ["mine"]


def test_keyword_relevant_prior_surfaces_across_directories():
    # The agent enters from the route file, but the relevant prior lives under
    # the components dir. Keyword overlap ("section") should still surface it.
    store = _store(
        _canonical(
            pattern="build each home section as a zone component",
            scope="src/components/Home/zones",
            rationale="self-contained sections",
        ),
        _canonical(
            pattern="use the email queue for outbound mail",
            scope="src/server/email",
            rationale="reliability",
        ),
    )
    results = get_priors_for_context(
        store,
        REPO,
        "src/routes/index.tsx homepage",
        "add a testimonials section to the homepage",
    )
    assert [p.pattern for p in results] == ["build each home section as a zone component"]


def test_unrelated_query_returns_nothing():
    # No scope relationship and no keyword overlap -> excluded (relevance floor).
    store = _store(
        _canonical(
            pattern="use the email queue for outbound mail",
            scope="src/server/email",
            rationale="reliability",
        ),
    )
    results = get_priors_for_context(
        store, REPO, "src/routes/index.tsx", "fix a typo in the footer"
    )
    assert results == []


def test_out_of_scope_priors_are_excluded():
    store = _store(
        _canonical(pattern="storage rule", scope="app/storage", rationale="r"),
        _canonical(pattern="ui rule", scope="app/ui", rationale="r"),
    )
    results = get_priors_for_context(store, REPO, "app/storage/db.py", "task")
    assert [p.pattern for p in results] == ["storage rule"]


def test_global_scope_priors_always_match():
    store = _store(_canonical(pattern="global rule", scope="", rationale="r"))
    results = get_priors_for_context(store, REPO, "anywhere/at/all.py", "task")
    assert [p.pattern for p in results] == ["global rule"]


def test_keyword_overlap_with_task_ranks_higher():
    store = _store(
        _canonical(pattern="use retries for network calls", scope="app", rationale="flaky"),
        _canonical(pattern="prefer dataclasses for config", scope="app", rationale="clarity"),
    )
    results = get_priors_for_context(store, REPO, "app", "add retries to the network client")
    assert results[0].pattern == "use retries for network calls"


def test_specific_subpath_outranks_broad_ancestor_for_multipath_area():
    # Regression for the real www query: the agent named several precise paths
    # (comma-joined), and a broad ancestor prior (src/routes) with no domain
    # keywords outranked the prior scoped to the exact sub-path the task was about.
    store = _store(
        _canonical(
            pattern="record sale events in the shared payments ledger",
            scope="src/routes/api/subscription",
            rationale="webhook handling writes to the ledger",
        ),
        _canonical(
            pattern="build route components as thin orchestrators",
            scope="src/routes",
            rationale="structure routes consistently",
        ),
    )
    area = (
        "src/routes/api/order_created, src/routes/api/subscription, "
        "src/components/SubmitFlow"
    )
    results = get_priors_for_context(store, REPO, area, "account for payment webhook logic")
    assert results[0].pattern == "record sale events in the shared payments ledger"


def test_rare_domain_keyword_outranks_common_token_overlap():
    # Two priors share the same scope and both overlap the task. The one matching
    # a RARE domain term (checkout) should beat one matching only common, low-signal
    # tokens (components/logic/shared) that appear all over the corpus.
    filler = [
        _canonical(
            pattern=f"use shared components and logic helper {i}",
            scope="app",
            rationale="general structure",
        )
        for i in range(8)
    ]
    rare = _canonical(pattern="use LemonSqueezy for checkout", scope="app", rationale="billing")
    common = _canonical(
        pattern="structure with shared components and logic", scope="app", rationale="general"
    )
    store = _store(rare, common, *filler)
    results = get_priors_for_context(
        store, REPO, "app", "wire up checkout using shared components and logic"
    )
    assert results[0].pattern == "use LemonSqueezy for checkout"


def test_sibling_directory_without_keywords_is_not_returned():
    # A sibling under the same parent dir (Home vs SubmitFlow under src/components)
    # is NOT relevant just for sharing a prefix; with no keyword overlap it is dropped.
    store = _store(
        _canonical(
            pattern="render homepage zones",
            scope="src/components/Home/zones",
            rationale="section layout",
        ),
        _canonical(
            pattern="drive the submit flow via SubmitFlow",
            scope="src/components/SubmitFlow",
            rationale="checkout",
        ),
    )
    results = get_priors_for_context(store, REPO, "src/components/SubmitFlow", "wire the checkout step")
    assert [p.pattern for p in results] == ["drive the submit flow via SubmitFlow"]


def test_response_is_capped_to_a_focused_set():
    # The served payload should be a focused set, not a 20-item dump.
    priors = [
        _canonical(pattern=f"rule {i}", scope="app", rationale="retries on the network client")
        for i in range(20)
    ]
    store = _store(*priors)
    results = get_priors_for_context(store, REPO, "app", "improve retries on the network client")
    assert len(results) <= 8


def test_closer_ancestor_scope_outranks_farther_ancestor():
    # Regression for a real db.ts query: the on-point prior lives in src/db (a
    # close ancestor of src/db/db.ts) but has ~no task keywords, while a generic
    # src-scoped prior matched a coincidental keyword ("app"). The closer ancestor
    # must win — both being "ancestors" should not flatten to the same weight.
    store = SQLitePriorStore(":memory:")
    far = _canonical(pattern="serve the app via an express node server", scope="src", rationale="infra")
    near = _canonical(
        pattern="wrap db ops with transient retry for turso resets",
        scope="src/db",
        rationale="reliability",
    )
    store.add(far)  # added first: a flat-weight tie would leave this on top
    store.add(near)
    results = get_priors_for_context(
        store, REPO, "src/db/db.ts", "add app credit ledger methods, atomic consume"
    )
    assert results[0].pattern.startswith("wrap db ops")


def test_submit_candidate_learning_stores_uncurated_agent_prior():
    store = SQLitePriorStore(":memory:")
    prior = submit_candidate_learning(
        store,
        repo=REPO,
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
        store, repo=REPO, pattern="p", scope="s", rationale="r", confidence="bogus"
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
