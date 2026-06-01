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

import math
import re

from metatron.events import Event, EventKind
from metatron.models import Confidence, Origin, Prior, SourceRef, Status
from metatron.storage.base import PriorStore

_CONFIDENCE_WEIGHT = {Confidence.LOW: 1, Confidence.MEDIUM: 2, Confidence.HIGH: 3}
_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "into", "use", "using",
    "add", "should", "when", "your", "you", "are", "but", "not", "all", "any",
}

# Relevance is scope_weight * _SCOPE_SCALE + idf_keyword_sum + confidence * _CONF_SCALE.
# Scope dominates ties (the agent named a path), but term weighting decides between
# priors at the same scope and lets a strong rare-keyword match beat a broad ancestor.
_SCOPE_SCALE = 10.0
_CONF_SCALE = 0.1


def get_priors_for_context(
    store: PriorStore,
    repo: str,
    file_path_or_area: str,
    task_description: str,
    *,
    limit: int = 8,
) -> list[Prior]:
    # Two relevance signals, neither a hard gate:
    #   1. scope — how specifically the prior's path relates to the area(s) the
    #      agent named (exact/inside > broad ancestor > sibling/none), so naming a
    #      precise sub-path surfaces the prior scoped there rather than generic
    #      advice for its parent directory.
    #   2. keywords — overlap with the task/area, weighted by inverse document
    #      frequency across this repo's canonical priors, so rare domain terms
    #      ("checkout", "webhook") count and boilerplate ("rather than", "commit")
    #      counts for ~nothing.
    # A prior with no scope relationship still surfaces on a real keyword match,
    # but a lone overlap on a corpus-common word carries almost no weight.
    priors = store.list(repo=repo, status=Status.CANONICAL)
    idf = _build_idf(priors)
    area_paths = _area_paths(file_path_or_area)
    query_tokens = _tokens(task_description) | _tokens(file_path_or_area)

    scored: list[tuple[Prior, float]] = []
    for prior in priors:
        score = _relevance(prior, area_paths, query_tokens, idf)
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


def format_priors(
    priors: list[Prior],
    *,
    query_id: str | None = None,
    version: str | None = None,
) -> str:
    """Render priors as compact structured context for an agent.

    When ``query_id``/``version`` are given, the output carries a header naming the
    query token (to reference in ``submit_feedback``) and the serving build, and the
    priors are numbered ``[1]``.. so feedback can rate them by index — never by the
    UUIDs that models mangle.
    """
    if not priors:
        body = "No matching priors."
    else:
        blocks = []
        for i, p in enumerate(priors, start=1):
            blocks.append(
                f"[{i}] [{p.confidence.value}] {p.pattern}\n"
                f"  scope: {p.scope or '(global)'}\n"
                f"  why: {p.rationale}"
            )
        body = "\n".join(blocks)

    if query_id is None and version is None:
        return body
    header = "metatron:query " + (query_id or "?")
    if version:
        header += f" · rev {version}"
    header += " (reference the query id in submit_feedback)"
    return f"{header}\n{body}"


def submit_feedback(
    store: PriorStore,
    event_store,
    *,
    repo: str,
    query_id: str = "",
    helpful: list[int] | tuple[int, ...] = (),
    unhelpful: list[int] | tuple[int, ...] = (),
    what_was_missing: str = "",
    missing_scope: str = "",
) -> tuple[Event, Prior | None]:
    """Record agent feedback on a served query and route any gap into the queue.

    Ratings are given as 1-based indices into the priors the named query served;
    they are mapped to real prior ids locally (bogus indices ignored), so the agent
    never echoes a UUID. ``what_was_missing`` becomes a **candidate** prior
    (``agent_feedback`` origin) for human curation — it never enters the canonical
    set, and ratings never mutate any prior. Returns the recorded FEEDBACK event and
    the created candidate (or None).
    """
    served = _served_prior_ids(event_store, query_id)
    helpful_ids = _resolve_indices(helpful, served)
    unhelpful_ids = _resolve_indices(unhelpful, served)

    candidate: Prior | None = None
    if what_was_missing.strip():
        candidate = store.add(
            Prior(
                repo=repo,
                pattern=what_was_missing.strip(),
                scope=missing_scope,
                rationale="Reported as missing via agent feedback.",
                confidence=Confidence.HIGH,  # flags it for prompt curation; still a candidate
                origin=Origin.AGENT_FEEDBACK,
            )
        )

    event = event_store.record(
        Event(
            repo=repo,
            kind=EventKind.FEEDBACK,
            query_ref=query_id,
            helpful_prior_ids=helpful_ids,
            unhelpful_prior_ids=unhelpful_ids,
            missing=what_was_missing.strip(),
            prior_ids=[candidate.id] if candidate else [],
        )
    )
    return event, candidate


def _served_prior_ids(event_store, query_id: str) -> list[str]:
    if not query_id:
        return []
    event = event_store.get(query_id)
    return list(event.prior_ids) if event is not None else []


def _resolve_indices(indices, served: list[str]) -> list[str]:
    """Map 1-based indices to served prior ids; out-of-range indices are ignored."""
    out = []
    for i in indices:
        if isinstance(i, int) and 1 <= i <= len(served):
            out.append(served[i - 1])
    return out


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


def _build_idf(priors: list[Prior]) -> dict[str, float]:
    """Inverse document frequency for tokens across the served priors.

    A token in nearly every prior (boilerplate like "commit"/"shared") gets an idf
    near 0; a rare domain term gets a high idf. Computed over the same set being
    ranked, so it is self-tuning per repo with no hand-maintained stopword list.
    """
    n = len(priors)
    df: dict[str, int] = {}
    for prior in priors:
        for tok in _tokens(f"{prior.pattern} {prior.rationale}"):
            df[tok] = df.get(tok, 0) + 1
    return {tok: math.log((n + 1) / (count + 1)) for tok, count in df.items()}


def _area_paths(area: str) -> list[str]:
    """Split an area into the individual path candidates the agent named.

    Agents commonly pass several comma- or space-separated paths
    ("src/routes/api/order_created, src/components/SubmitFlow"). Scope is matched
    against the best of these so a precise sub-path is rewarded, not diluted by
    being one item in a blob.
    """
    return [part.strip("/") for part in re.split(r"[,\s]+", area.strip()) if part.strip("/")]


def _relevance(
    prior: Prior, area_paths: list[str], query_tokens: set[str], idf: dict[str, float]
) -> float:
    """Relevance score; 0 means "no signal" (filtered out).

    Scope relationship dominates ties, then idf-weighted keyword overlap, then
    confidence — so the prior scoped to the exact area ranks first, but a strong
    rare-keyword match still beats a broad ancestor with no keyword overlap.
    """
    scope = _scope_weight(prior.scope, area_paths)
    overlap = _tokens(f"{prior.pattern} {prior.rationale}") & query_tokens
    keywords = sum(idf.get(tok, 0.0) for tok in overlap)
    if scope == 0 and keywords == 0:
        return 0.0
    return scope * _SCOPE_SCALE + keywords + _CONFIDENCE_WEIGHT[prior.confidence] * _CONF_SCALE


def _scope_weight(prior_scope: str, area_paths: list[str]) -> float:
    """Best scope relationship between a prior and any of the queried paths.

    Rewards specificity: an exact or deeper match (the prior is the area, or sits
    *inside* it) outweighs a broad ancestor that merely contains the area, and
    siblings (sharing only a parent dir) score nothing.
    """
    if prior_scope == "":  # global prior — applies everywhere, weakly
        return 1.0
    return max((_pair_scope(prior_scope, area) for area in area_paths), default=0.0)


def _pair_scope(prior_scope: str, area: str) -> float:
    scope = prior_scope.strip("/").split("/")
    target = area.strip("/").split("/")
    shared = 0
    for a, b in zip(scope, target):
        if a != b:
            break
        shared += 1
    if shared == 0:
        return 0.0
    if shared == len(scope) == len(target):  # exact match — most specific
        return 3.0 + shared
    if shared == len(target):  # prior sits inside the queried area — specific
        return 2.0 + shared
    if shared == len(scope):  # prior is an ancestor of the area
        # Weight by how *close* the ancestor is: a prior scoped src/db is a far
        # better match for src/db/db.ts than one scoped src. Flattening every
        # ancestor to the same weight let generic top-level priors crowd out the
        # prior whose scope is the file's own directory.
        return float(shared)
    return 0.0  # siblings: share a parent dir but diverge — not relevant
