"""Retrieval and submission logic behind the MCP tools.

Kept independent of the MCP server so it can be tested directly. Two operations:

- ``get_priors_for_context`` — serve **canonical only** priors relevant to an
  area, ranked by keyword overlap with the task, confidence, and scope
  specificity (resolved decisions: canonical-only serving; scope-match + keyword
  ranking, embeddings deferred).
- ``submit_candidate_learning`` — accept a prior from an agent and store it as an
  uncurated ``candidate`` of ``agent_submitted`` origin. It never auto-promotes.
"""

from __future__ import annotations

import re

from metatron.models import Confidence, Origin, Prior, SourceRef, Status
from metatron.storage.base import PriorStore

_CONFIDENCE_WEIGHT = {Confidence.LOW: 1, Confidence.MEDIUM: 2, Confidence.HIGH: 3}
_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "into", "use", "using",
    "add", "should", "when", "your", "you", "are", "but", "not", "all", "any",
}


def get_priors_for_context(
    store: PriorStore,
    repo: str,
    file_path_or_area: str,
    task_description: str,
    *,
    limit: int = 20,
) -> list[Prior]:
    # Scope is a ranking signal, not a hard gate: a prior is relevant if it
    # overlaps the area's path OR shares keywords with the task/area. This lets
    # textually-relevant priors surface even when the agent enters from a
    # different directory (e.g. a route file) than where the prior lives.
    query_tokens = _tokens(task_description) | _tokens(file_path_or_area)
    scored: list[tuple[Prior, int]] = []
    for prior in store.list(repo=repo, status=Status.CANONICAL):
        score = _relevance(prior, file_path_or_area, query_tokens)
        if score > 0:
            scored.append((prior, score))
    scored.sort(key=lambda ps: ps[1], reverse=True)
    return [prior for prior, _ in scored[:limit]]


def submit_candidate_learning(
    store: PriorStore,
    *,
    repo: str,
    pattern: str,
    scope: str,
    rationale: str,
    confidence: str | Confidence = Confidence.MEDIUM,
    source_refs: list[SourceRef] | None = None,
) -> Prior:
    prior = Prior(
        repo=repo,
        pattern=pattern,
        scope=scope,
        rationale=rationale,
        confidence=_coerce_confidence(confidence),
        origin=Origin.AGENT_SUBMITTED,
        source_refs=source_refs or [],
    )
    return store.add(prior)


def format_priors(priors: list[Prior]) -> str:
    """Render priors as compact structured context for an agent."""
    if not priors:
        return "No matching priors."
    blocks = []
    for p in priors:
        block = (
            f"- [{p.confidence.value}] {p.pattern}\n"
            f"  scope: {p.scope or '(global)'}\n"
            f"  why: {p.rationale}"
        )
        blocks.append(block)
    return "\n".join(blocks)


def _coerce_confidence(value: str | Confidence) -> Confidence:
    try:
        return Confidence(value)
    except ValueError:
        return Confidence.MEDIUM


def _tokens(text: str) -> set[str]:
    return {
        tok
        for tok in re.split(r"[^a-z0-9]+", text.lower())
        if len(tok) >= 3 and tok not in _STOPWORDS
    }


def _relevance(prior: Prior, area: str, query_tokens: set[str]) -> int:
    """Relevance score; 0 means "no signal" (filtered out).

    Scope relationship dominates, then keyword overlap, then confidence — so
    exact-path priors rank first, but a strong keyword match in another directory
    still beats nothing.
    """
    scope = _scope_score(prior.scope, area)
    keywords = len(_tokens(f"{prior.pattern} {prior.rationale}") & query_tokens)
    if scope == 0 and keywords == 0:
        return 0
    return scope * 100 + keywords * 10 + _CONFIDENCE_WEIGHT[prior.confidence]


def _scope_score(prior_scope: str, area: str) -> int:
    """How strongly a prior's scope relates to the queried area (0 = unrelated)."""
    if prior_scope == "":  # global prior — applies everywhere, weakly
        return 1
    scope = prior_scope.strip("/")
    target = area.strip("/")
    if target == scope:
        return 4
    if target.startswith(scope + "/"):  # the area sits inside the prior's scope
        return 3
    if scope.startswith(target + "/"):  # the prior's scope sits inside the area
        return 2
    return 0
