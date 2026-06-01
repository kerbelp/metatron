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
    # Instruction/filler language: common in task phrasing, absent from priors, so
    # idf (computed over priors) wrongly rates it rare/high. Stop it so keyword
    # relevance reflects domain terms, not "change the X to Y instead" boilerplate.
    "change", "find", "its", "only", "instead", "free", "make", "update", "new",
    "set", "get", "via", "per", "each", "one", "want", "need", "like", "also",
    # Generic path/structure tokens that carry no domain meaning as keywords.
    "src", "lib", "app", "index", "components", "component",
}

# Relevance is scope_weight * _SCOPE_SCALE + idf_keyword_sum + confidence * _CONF_SCALE.
# Scope dominates ties (the agent named a path), but term weighting decides between
# priors at the same scope and lets a strong rare-keyword match beat a broad ancestor.
_SCOPE_SCALE = 10.0
_CONF_SCALE = 0.1
# Of the returned slots, hold this many for the best pure task-keyword matches so a
# relevant prior scoped outside the named area isn't crowded out by same-scope priors.
_RESERVED_KEYWORD_SLOTS = 3


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
    #   2. keywords — overlap with the *task description*, weighted by inverse
    #      document frequency across this repo's canonical priors, so rare domain
    #      terms ("checkout", "webhook") count and boilerplate counts for ~nothing.
    # Area path segments (src, components, the dir name) are deliberately NOT used as
    # keywords — they're the scope signal, and as keywords they only inflate every
    # cross-scope prior with noise. A prior with no scope relationship still surfaces
    # on a real task keyword match; a lone corpus-common overlap carries almost none.
    priors = store.list(repo=repo, status=Status.CANONICAL)
    idf = _build_idf(priors)
    area_paths = _area_paths(file_path_or_area)
    query_tokens = _tokens(task_description)

    scored: list[tuple[Prior, float]] = []
    by_keyword: list[tuple[Prior, float]] = []
    for prior in priors:
        score = _relevance(prior, area_paths, query_tokens, idf)
        if score > 0:
            scored.append((prior, score))
        kw = _keyword_score(prior, query_tokens, idf)
        if kw > 0:
            by_keyword.append((prior, kw))
    scored.sort(key=lambda ps: ps[1], reverse=True)
    by_keyword.sort(key=lambda ps: ps[1], reverse=True)

    # Fill most slots by the scope-led combined score, but reserve a few for the
    # strongest *task-keyword* matches — otherwise a directory full of generic
    # same-scope priors (each scoring ~scope*scale) shuts out a genuinely relevant
    # prior that happens to live elsewhere (e.g. the link/url convention in
    # src/utils/i18n for an href-editing task). Reserved slots only kick in when
    # such keyword matches exist; with no keyword signal, scope takes every slot.
    primary_n = max(0, limit - _RESERVED_KEYWORD_SLOTS) if by_keyword else limit
    picked: list[Prior] = []
    seen: set[str] = set()

    def take(pairs: list[tuple[Prior, float]], cap: int) -> None:
        for prior, _ in pairs:
            if len(picked) >= cap:
                break
            if prior.id not in seen:
                picked.append(prior)
                seen.add(prior.id)

    take(scored, primary_n)       # scope-led primary picks
    take(by_keyword, limit)       # reserved slots: best keyword matches not yet picked
    take(scored, limit)           # backfill if keyword matches were few
    return picked[:limit]


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
) -> Event:
    """Capture agent feedback on a served query. Capture only — no candidate here.

    Ratings are given as 1-based indices into the priors the named query served;
    they are mapped to real prior ids locally (bogus indices ignored), so the agent
    never echoes a UUID. ``what_was_missing`` is recorded as the gap text (with the
    scope hint in ``area``) for the human-gated Opus refiner to later reshape into
    *structured* candidate priors — nothing enters the queue here, and ratings never
    mutate any prior. Returns the recorded FEEDBACK event.
    """
    served = _served_prior_ids(event_store, query_id)
    return event_store.record(
        Event(
            repo=repo,
            kind=EventKind.FEEDBACK,
            area=missing_scope,  # scope hint for the refiner
            query_ref=query_id,
            helpful_prior_ids=_resolve_indices(helpful, served),
            unhelpful_prior_ids=_resolve_indices(unhelpful, served),
            missing=what_was_missing.strip(),
        )
    )


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


# Light suffix stemmer so morphological variants match: the task says "owner",
# the prior says "ownership"; "link" vs "links"; "redirect" vs "redirects". Applied
# to every token (query, prior, and idf) so the vocabulary is consistent. Stripping
# is iterative and refuses to leave a stem shorter than 3 chars, which keeps short
# domain words ("api", "css", "user") intact. No "er"/"ers" — it over-stems.
_STEM_SUFFIXES = (
    "izations", "ization", "ships", "ship", "ments", "ment", "sions", "sion",
    "tions", "tion", "ness", "ings", "ing", "ies", "es", "ed", "s",
)


def _stem(tok: str) -> str:
    changed = True
    while changed and len(tok) > 3:
        changed = False
        for suf in _STEM_SUFFIXES:
            if tok.endswith(suf) and len(tok) - len(suf) >= 3:
                tok, changed = tok[: -len(suf)], True
                break
    return tok


def _tokens(text: str) -> set[str]:
    return {
        _stem(tok)
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
    keywords = _keyword_score(prior, query_tokens, idf)
    if scope == 0 and keywords == 0:
        return 0.0
    return scope * _SCOPE_SCALE + keywords + _CONFIDENCE_WEIGHT[prior.confidence] * _CONF_SCALE


def _keyword_score(prior: Prior, query_tokens: set[str], idf: dict[str, float]) -> float:
    """idf-weighted overlap between the prior's text and the task/area tokens.

    The pure task-relevance signal — no scope, no confidence — used both inside
    ``_relevance`` and to pick the reserved keyword slots in retrieval.
    """
    overlap = _tokens(f"{prior.pattern} {prior.rationale}") & query_tokens
    return sum(idf.get(tok, 0.0) for tok in overlap)


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
