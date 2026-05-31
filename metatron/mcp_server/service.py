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
    task_tokens = _tokens(task_description)
    relevant = [
        p
        for p in store.list(repo=repo, status=Status.CANONICAL)
        if _in_scope(p.scope, file_path_or_area)
    ]
    relevant.sort(
        key=lambda p: _score(p, file_path_or_area, task_tokens), reverse=True
    )
    return relevant[:limit]


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


def _in_scope(prior_scope: str, area: str) -> bool:
    if prior_scope == "":  # global prior
        return True
    scope = prior_scope.strip("/")
    target = area.strip("/")
    return (
        target == scope
        or target.startswith(scope + "/")
        or scope.startswith(target + "/")
    )


def _score(prior: Prior, area: str, task_tokens: set[str]) -> int:
    overlap = len(_tokens(f"{prior.pattern} {prior.rationale}") & task_tokens)
    exact = 2 if prior.scope.strip("/") == area.strip("/") else 0
    return overlap * 10 + _CONFIDENCE_WEIGHT[prior.confidence] + exact
