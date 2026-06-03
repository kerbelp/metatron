"""Tests for the MCP service logic (retrieval + submission), server-independent."""

from metatron.mcp_server.service import (
    _stem,
    _tokens,
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


def test_helpfulness_reorders_peers_within_a_tier():
    # Two equally-relevant on-scope priors; the higher-rated one is served first.
    loved = _canonical(pattern="webhook ledger handling", scope="src/api", rationale="r")
    meh = _canonical(pattern="webhook ledger handling", scope="src/api", rationale="r")
    store = _store(meh, loved)  # insertion order puts meh first absent ratings

    results = get_priors_for_context(
        store, REPO, "src/api", "webhook ledger",
        helpfulness={loved.id: 1.0},  # loved gets the full positive nudge
    )
    assert results[0].id == loved.id


def test_helpfulness_cannot_lift_a_prior_across_a_scope_tier():
    # A loved off-scope prior must NOT outrank an on-scope prior with the same
    # keywords — helpfulness only reorders within a tier, never across the gate.
    on_scope = _canonical(pattern="webhook ledger retry", scope="src/api/orders", rationale="r")
    off_scope = _canonical(pattern="webhook ledger retry", scope="docs/notes", rationale="r")
    store = _store(on_scope, off_scope)

    results = get_priors_for_context(
        store, REPO, "src/api/orders", "webhook ledger retry",
        helpfulness={off_scope.id: 1.0, on_scope.id: -1.0},  # try hard to invert it
    )
    assert results.index(_by_id(results, on_scope.id)) < results.index(_by_id(results, off_scope.id))


def _by_id(priors, pid):
    return next(p for p in priors if p.id == pid)


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


def test_global_prior_needs_keyword_evidence_not_just_scope():
    # "Prefer no priors over plausible filler": a global prior with no keyword
    # overlap must NOT be served for an unrelated task (the founding-incident rule).
    store = _store(_canonical(pattern="prefer composition", scope="", rationale="r"))
    results = get_priors_for_context(store, REPO, "src/routes/api/payments", "refund a webhook")
    assert results == []


def test_global_prior_surfaces_on_keyword_match():
    # needs a corpus where "webhook" is distinguishing (idf > 0), as in any real repo
    store = _store(
        _canonical(pattern="always handle webhook retries", scope="", rationale="r"),
        _canonical(pattern="compose home zones", scope="src/components/Home", rationale="r"),
        _canonical(pattern="route strings via urls helper", scope="src/utils/i18n", rationale="r"),
        _canonical(pattern="render FAQ with details elements", scope="src/components/App", rationale="r"),
    )
    results = get_priors_for_context(store, REPO, "src/routes/api/payments", "refund a webhook")
    assert "always handle webhook retries" in [p.pattern for p in results]


def test_returns_empty_over_filler_when_nothing_relates():
    # No scope relationship to the area and no keyword overlap -> return nothing.
    store = _store(
        _canonical(pattern="compose home zones", scope="src/components/Home", rationale="r"),
        _canonical(pattern="prefer composition", scope="", rationale="r"),
    )
    results = get_priors_for_context(store, REPO, "src/routes/api/payments", "refund a webhook")
    assert results == []


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


# --- stemming: morphological variants should match on keywords ---

def test_tokens_stem_unifies_morphological_variants():
    # the task says "owner", the prior says "ownership"; "link" vs "links"
    assert _tokens("owner") & _tokens("ownership")
    assert _tokens("link") & _tokens("links")
    assert _tokens("redirect") & _tokens("redirects")
    assert _tokens("route") & _tokens("routes")
    assert _tokens("category") & _tokens("categories")


def test_stemmer_does_not_mangle_double_letter_and_us_is_words():
    # Conservative: these must be left intact (the old stemmer ate them:
    # class->cla, access->acc, status->statu, success->succ).
    for w in ("class", "access", "process", "success", "address",
              "status", "analysis", "session", "business"):
        assert _stem(w) == w, f"{w} should be stemmed to itself, got {_stem(w)!r}"


def test_stemmer_avoids_false_collisions():
    # access/process must NOT collapse to the same stem (acc/proc) and match.
    assert not (_tokens("access control") & _tokens("process queue"))


# --- P1b: alias canonicalization + code-literal preservation ---

def test_alias_unifies_link_vocabulary():
    # href/url/link are the same hyperlink-target concept -> one canonical token.
    # (route/anchor/slug deliberately excluded — different concept, hurts precision.)
    assert _tokens("href") == _tokens("url") == _tokens("link") == _tokens("hyperlink")


def test_alias_unifies_auth_vocabulary():
    assert _tokens("clerk") == _tokens("authentication") == _tokens("authorize")


def test_alias_closes_href_url_vocabulary_gap():
    # task says "href"; the relevant prior says only "urls/links" and lives elsewhere.
    # Without aliasing the only overlap is the (common) word "dashboard" -> filtered.
    area = "src/components/Button"
    filler = [_canonical(pattern=f"compose layout piece {i}", scope=area, rationale="x")
              for i in range(4)]
    commons = [_canonical(pattern=f"dashboard widget {i} loads data", scope=f"src/d{i}", rationale="r")
               for i in range(6)]  # make "dashboard" common (low idf)
    link_prior = _canonical(pattern="build dashboard links through the urls helper",
                            scope="src/utils/i18n", rationale="r")
    store = _store(*filler, *commons, link_prior)
    results = get_priors_for_context(store, REPO, area, "fix the href on the dashboard", limit=8)
    assert any(p.scope == "src/utils/i18n" for p in results)


def test_code_literal_preserved_as_single_token():
    assert "order_created" in _tokens("mirror the order_created webhook chain")
    assert "db_insertapplication" in _tokens("call db.insertApplication carefully")


def test_stemming_surfaces_keyword_match_despite_suffix():
    # prior phrased with "-ship"/"-s" suffixes still matches a bare-stem task
    store = _store(
        _canonical(pattern="filler one", scope="app", rationale="x"),
        _canonical(pattern="filler two", scope="app", rationale="y"),
        _canonical(pattern="Resolve resource ownership and gate owners",
                   scope="src/utils/ownership", rationale="z"),
    )
    results = get_priors_for_context(
        store, REPO, "app", "restrict this to the resource owner", limit=8
    )
    assert any("ownership" in p.pattern for p in results)


# --- reserved slots: a strong cross-scope keyword match is not shut out ---

def test_reserved_slots_surface_cross_scope_keyword_match():
    # The agent names src/components/ApplicationPage and many generic priors live
    # there (exact-scope, no task-keyword overlap). One prior elsewhere is the real
    # answer to the task. Pure scope ranking buries it; reserved slots surface it.
    area = "src/components/ApplicationPage"
    generic = [
        _canonical(pattern=f"structure rule {i}", scope=area, rationale="layout")
        for i in range(8)
    ]
    link_prior = _canonical(
        pattern="Build internal links through the urls helper instead of hardcoding hrefs",
        scope="src/utils/i18n", rationale="routing convention",
    )
    store = _store(*generic, link_prior)

    results = get_priors_for_context(
        store, REPO, area,
        "change the CTA href to /blog/write using internal links", limit=8,
    )
    assert any(p.scope == "src/utils/i18n" for p in results), \
        "the keyword-relevant cross-scope prior should occupy a reserved slot"


def test_single_weak_keyword_does_not_admit_out_of_scope_prior():
    # P1a: a cross-scope prior matching only ONE low-value token ("write", common in
    # this corpus so low idf) must NOT be admitted as filler.
    area = "src/components/App"
    same_scope = [_canonical(pattern=f"structure rule {i}", scope=area, rationale="layout")
                  for i in range(5)]
    writers = [_canonical(pattern=f"write {x} to disk carefully", scope=f"src/io/{x}", rationale="io")
               for x in ("logs", "cache", "temp", "blob", "queue", "meta")]  # make "write" common
    docs = _canonical(pattern="write a dedicated spec document for each feature",
                      scope="docs/specs", rationale="process")
    store = _store(*same_scope, *writers, docs)
    results = get_priors_for_context(store, REPO, area, "write a free review for the page", limit=8)
    assert all(p.scope != "docs/specs" for p in results)


def test_more_than_three_topical_outsiders_can_be_returned():
    # P2: with generic same-scope filler present, strong cross-scope matches are not
    # capped at 3 — they fill ahead of keyword-less same-scope priors.
    area = "src/components/ApplicationPage"
    structure = [_canonical(pattern=f"compose discrete piece {i}", scope=area, rationale="layout")
                 for i in range(8)]
    outsiders = [
        _canonical(pattern="authenticate webhook payments via clerk auth",
                   scope="src/routes/api/payments", rationale="r"),
        _canonical(pattern="record ledger entries for webhook payments",
                   scope="src/db/ledger", rationale="r"),
        _canonical(pattern="send email report of webhook payments daily",
                   scope="src/jobs/report", rationale="r"),
        _canonical(pattern="render admin payments table with webhook status",
                   scope="src/views/admin", rationale="r"),
        _canonical(pattern="ensure webhook payments stay idempotent on retry",
                   scope="src/utils/idempotency", rationale="r"),
    ]
    store = _store(*structure, *outsiders)
    task = "handle webhook payments: ledger, email report, admin table, idempotent retry"
    results = get_priors_for_context(store, REPO, area, task, limit=8)
    n_outsiders = sum(1 for p in results if p.scope != area)
    assert n_outsiders >= 4, f"expected >3 topical outsiders, got {n_outsiders}"


def test_weak_same_scope_keyword_does_not_block_strong_cross_scope():
    # P1: 8 same-scope priors overlap the task only on a COMMON word ("review", low
    # idf); one cross-scope prior matches a RARE term ("webhook"). Tier A must not be
    # filled by weak same-scope hits and bury the strong cross-scope evidence — a weak
    # same-scope match is demoted to the generic tier, behind strong cross-scope.
    area = "src/components/ApplicationPage"
    weak = [_canonical(pattern=f"review the layout for rule {i}", scope=area, rationale="review")
            for i in range(8)]  # "review" everywhere -> low idf, weak evidence
    strong = _canonical(pattern="verify the webhook signature before processing",
                        scope="src/routes/api/payments", rationale="security")
    store = _store(*weak, strong)
    results = get_priors_for_context(
        store, REPO, area, "review the webhook handling on this page", limit=8
    )
    assert any(p.scope == "src/routes/api/payments" for p in results), \
        "a strong cross-scope match must not be shut out by weak same-scope keyword hits"


def test_path_literal_preserved_as_single_token():
    # P2a: "/blog/write" should survive as one rare token, not split into blog + write.
    assert "blog_write" in _tokens("change the CTA href to /blog/write")


def test_kebab_literal_unifies_with_snake_case():
    # P2a: event names appear kebab in prose ("order-created") and snake in code
    # ("order_created"); both should canonicalize to the same literal token so a task
    # phrased either way matches a prior phrased the other.
    assert "order_created" in _tokens("listen for the order-created event")
    assert _tokens("emit order-created") & _tokens("the order_created webhook")


def test_reserved_slots_still_return_scope_matches_when_no_keyword_signal():
    # No cross-scope keyword match exists: all 8 slots go to the scope matches.
    area = "src/components/ApplicationPage"
    generic = [
        _canonical(pattern=f"structure rule {i}", scope=area, rationale="layout")
        for i in range(10)
    ]
    store = _store(*generic)
    results = get_priors_for_context(store, REPO, area, "unrelated task words", limit=8)
    assert len(results) == 8
    assert all(p.scope == area for p in results)
