"""Retrieval and submission logic behind the MCP tools.

Kept independent of the MCP server so it can be tested directly. Two operations:

- ``get_decisions_for_context`` — serve **canonical only** decisions relevant to an
  area, ranked by keyword overlap with the task, confidence, and scope
  specificity (resolved decisions: canonical-only serving; scope-match + keyword
  ranking, embeddings deferred).
- ``submit_candidate_decision`` — accept a decision from an agent and store it as an
  uncurated ``candidate`` of ``agent_submitted`` origin. It never auto-promotes.
"""

from __future__ import annotations

import math
import re

from metatron.events import Event, EventKind
from metatron.models import Confidence, Origin, Decision, SourceRef, Status, sanitize_keywords
from metatron.storage.base import DecisionStore

_CONFIDENCE_WEIGHT = {Confidence.LOW: 1, Confidence.MEDIUM: 2, Confidence.HIGH: 3}
_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "into", "use", "using",
    "add", "should", "when", "your", "you", "are", "but", "not", "all", "any",
    # Instruction/filler language: common in task phrasing, absent from decisions, so
    # idf (computed over decisions) wrongly rates it rare/high. Stop it so keyword
    # relevance reflects domain terms, not "change the X to Y instead" boilerplate.
    "change", "find", "its", "only", "instead", "free", "make", "update", "new",
    "set", "get", "via", "per", "each", "one", "want", "need", "like", "also",
    # Generic path/structure tokens that carry no domain meaning as keywords.
    "src", "lib", "app", "index", "components", "component",
}

# Ranking weights. Scope and keyword evidence are combined for ordering *within* a
# tier; the tiering itself (see get_decisions_for_context) decides admission, so scope
# no longer absolutely dominates — a strong topical match outranks generic same-scope.
_SCOPE_SCALE = 10.0
_CONF_SCALE = 0.1
# Helpfulness weight. Agent ratings (see metatron/feedback_score.py) arrive as a
# centered signal in roughly [-1, 1]; this scales it into the within-tier sort. At
# 2.0 a loved decision gets a nudge comparable to a couple of keyword-idf hits — enough
# to reorder peers, never enough to cross a tier (admission is decided before this
# term is applied), so helpfulness can't override the scope/keyword relevance gate.
_HELP_SCALE = 2.0
# Evidence floor for decisions with no scope relationship to the area (global/sibling):
# admit only on real lexical evidence — at least this many distinct meaningful token
# overlaps, OR a single hit on a term rare enough to clear _idf_evidence_threshold.
# Stops a lone common token (e.g. "write") from admitting off-topic filler.
_MIN_KEYWORD_HITS = 2

def get_decisions_for_context(
    store: DecisionStore,
    repo: str,
    file_path_or_area: str,
    task_description: str,
    *,
    limit: int = 8,
    helpfulness: dict[str, float] | None = None,
) -> list[Decision]:
    # Two relevance signals, neither a hard gate:
    #   1. scope — how specifically the decision's path relates to the area(s) the
    #      agent named (exact/inside > broad ancestor > sibling/none), so naming a
    #      precise sub-path surfaces the decision scoped there rather than generic
    #      advice for its parent directory.
    #   2. keywords — overlap with the *task description*, weighted by inverse
    #      document frequency across this repo's canonical decisions, so rare domain
    #      terms ("checkout", "webhook") count and boilerplate counts for ~nothing.
    # Area path segments (src, components, the dir name) are deliberately NOT used as
    # keywords — they're the scope signal, and as keywords they only inflate every
    # cross-scope decision with noise. A decision with no scope relationship still surfaces
    # on a real task keyword match; a lone corpus-common overlap carries almost none.
    decisions = store.list(repo=repo, status=Status.CANONICAL)
    idf = _build_idf(decisions)
    area_paths = _area_paths(file_path_or_area)
    query_tokens = _tokens(task_description)
    threshold = _idf_evidence_threshold(idf)
    conf = lambda p: _CONFIDENCE_WEIGHT[p.confidence] * _CONF_SCALE
    # Agent-rated helpfulness, applied only to the *within-tier* sort score below.
    # Tier admission is decided before this term, so a loved decision can outrank its
    # peers but never jump the scope/keyword gate into a higher tier.
    help_score = helpfulness or {}
    helpful = lambda p: _HELP_SCALE * help_score.get(p.id, 0.0)

    # Admission by tier, filled in priority order up to `limit`. This replaces the old
    # "scope*10 swamps keywords, then a fixed 3 reserved slots" scheme, which both
    # admitted single-weak-keyword filler and capped real cross-scope recall.
    on_scope_topical: list[tuple[Decision, float]] = []   # A: in/under the area AND task-relevant
    cross_scope_topical: list[tuple[Decision, float]] = []  # B: elsewhere but strong lexical evidence
    on_scope_generic: list[tuple[Decision, float]] = []   # C: in/under the area, no task keyword
    for decision in decisions:
        scope = _scope_weight(decision.scope, area_paths)
        hits = _decision_tokens(decision) & query_tokens
        kw = sum(idf.get(tok, 0.0) for tok in hits)
        # The SAME evidence floor gates topical admission for both scopes. A same-scope
        # decision counts as topical only if its keyword overlap is real (≥2 distinct hits,
        # or one rare term); a lone common-word overlap ("review") is weak and drops to
        # the generic tier instead of pre-empting strong cross-scope evidence (P1).
        strong = _clears_evidence_floor(hits, idf, threshold)
        if scope > 0 and strong:
            on_scope_topical.append((decision, scope * _SCOPE_SCALE + kw + conf(decision) + helpful(decision)))
        elif scope > 0:
            on_scope_generic.append((decision, scope * _SCOPE_SCALE + kw + conf(decision) + helpful(decision)))
        elif strong:
            cross_scope_topical.append((decision, kw + conf(decision) + helpful(decision)))
        # else: no scope relationship and insufficient lexical evidence -> dropped
        #       (prefer returning nothing over plausible filler).

    picked: list[Decision] = []
    for tier in (on_scope_topical, cross_scope_topical, on_scope_generic):
        tier.sort(key=lambda ps: ps[1], reverse=True)
        for decision, _ in tier:
            if len(picked) >= limit:
                return picked
            picked.append(decision)
    return picked


# Near-duplicate gate for incoming candidates. Pattern-token Jaccard at or above
# this is "the same rule in different words": agents and the feedback refiner restate
# conventions the store already holds, and every restatement is another row a human
# has to triage. Matching runs against ALL statuses on purpose — a candidate dupe is
# queue spam, a canonical dupe is already served, and a rejected dupe was already
# turned down by a human; none should (re-)enter the queue.
_DUPLICATE_SIMILARITY = 0.75
# Below this many meaningful tokens, overlap is too little signal to call two rules
# the same ("use the gap helper" vs "mind the gap helper"); never dedupe.
_MIN_DUPLICATE_TOKENS = 3


def find_duplicate(store: DecisionStore, *, repo: str, pattern: str) -> Decision | None:
    """The existing decision ``pattern`` near-duplicates, if any (highest overlap wins)."""
    new_tokens = _tokens(pattern)
    if len(new_tokens) < _MIN_DUPLICATE_TOKENS:
        return None
    best: Decision | None = None
    best_sim = _DUPLICATE_SIMILARITY
    for existing in store.list(repo=repo):
        tokens = _tokens(existing.pattern)
        if len(tokens) < _MIN_DUPLICATE_TOKENS:
            continue
        sim = len(new_tokens & tokens) / len(new_tokens | tokens)
        if sim >= best_sim:
            best, best_sim = existing, sim
    return best


def submit_candidate_decision(
    store: DecisionStore,
    *,
    repo: str,
    pattern: str,
    scope: str,
    rationale: str,
    confidence: str | Confidence = Confidence.MEDIUM,
    source_refs: list[SourceRef] | None = None,
    keywords: list[str] | None = None,
) -> Decision:
    duplicate = find_duplicate(store, repo=repo, pattern=pattern)
    if duplicate is not None:
        return duplicate
    decision = Decision(
        repo=repo,
        pattern=pattern,
        # Normalized at write time so the stored corpus stays clean; serve-time
        # matching applies the same normalization for rows stored before this.
        scope=_normalize_scope(scope),
        rationale=rationale,
        keywords=sanitize_keywords(keywords),
        confidence=_coerce_confidence(confidence),
        origin=Origin.AGENT_SUBMITTED,
        source_refs=source_refs or [],
    )
    return store.add(decision)


def format_decisions(
    decisions: list[Decision],
    *,
    query_id: str | None = None,
    version: str | None = None,
) -> str:
    """Render decisions as compact structured context for an agent.

    When ``query_id``/``version`` are given, the output carries a header naming the
    query token (to reference in ``submit_feedback``) and the serving build, and the
    decisions are numbered ``[1]``.. so feedback can rate them by index — never by the
    UUIDs that models mangle.
    """
    if not decisions:
        body = "No matching decisions."
    else:
        blocks = []
        for i, p in enumerate(decisions, start=1):
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
    store: DecisionStore,
    event_store,
    *,
    repo: str,
    query_id: str = "",
    helpful: list[int] | tuple[int, ...] = (),
    unhelpful: list[int] | tuple[int, ...] = (),
    ratings: dict | None = None,
    what_was_missing: str = "",
    missing_scope: str = "",
) -> Event:
    """Capture agent feedback on a served query. Capture only — no candidate here.

    Ratings are given as 1-based indices into the decisions the named query served;
    they are mapped to real decision ids locally (bogus indices ignored), so the agent
    never echoes a UUID. ``ratings`` is a graded ``{index: 1..10}`` map; out-of-range
    indices and out-of-band scores are dropped. When ``ratings`` is given without
    explicit ``helpful``/``unhelpful``, the binary lists are derived from it (≥7 →
    helpful, ≤4 → noise) so existing tallies keep working. ``what_was_missing`` is
    recorded as the gap text (with the scope hint in ``area``) for the human-gated
    Opus refiner to later reshape into *structured* candidate decisions — nothing enters
    the queue here. The graded scores feed serve-time ranking (see
    :mod:`metatron.feedback_score`) but never mutate a decision's status. Returns the
    recorded FEEDBACK event.
    """
    served = _served_decision_ids(event_store, query_id)
    resolved_ratings = _resolve_ratings(ratings or {}, served)
    helpful_ids = _resolve_indices(helpful, served)
    unhelpful_ids = _resolve_indices(unhelpful, served)
    if resolved_ratings and not helpful_ids and not unhelpful_ids:
        helpful_ids = [pid for pid, s in resolved_ratings.items() if s >= 7]
        unhelpful_ids = [pid for pid, s in resolved_ratings.items() if s <= 4]
    return event_store.record(
        Event(
            repo=repo,
            kind=EventKind.FEEDBACK,
            area=missing_scope,  # scope hint for the refiner
            query_ref=query_id,
            helpful_decision_ids=helpful_ids,
            unhelpful_decision_ids=unhelpful_ids,
            ratings=resolved_ratings,
            missing=what_was_missing.strip(),
        )
    )


def _served_decision_ids(event_store, query_id: str) -> list[str]:
    if not query_id:
        return []
    event = event_store.get(query_id)
    return list(event.decision_ids) if event is not None else []


def _resolve_indices(indices, served: list[str]) -> list[str]:
    """Map 1-based indices to served decision ids; out-of-range indices are ignored."""
    out = []
    for i in indices:
        if isinstance(i, int) and 1 <= i <= len(served):
            out.append(served[i - 1])
    return out


def _resolve_ratings(ratings: dict, served: list[str]) -> dict[str, int]:
    """Map a ``{index: score}`` rating map to ``{decision_id: score}``.

    Keys are 1-based indices into the served decisions (ints, or the string ints models
    emit as JSON object keys). Scores must be integers in 1..10. Out-of-range indices
    and out-of-band scores are dropped — a bogus rating is simply ignored, never an
    error, and last write wins if an index repeats.
    """
    out: dict[str, int] = {}
    for key, score in ratings.items():
        try:
            i, s = int(key), int(score)
        except (TypeError, ValueError):
            continue
        if 1 <= i <= len(served) and 1 <= s <= 10:
            out[served[i - 1]] = s
    return out


def _coerce_confidence(value: str | Confidence) -> Confidence:
    try:
        return Confidence(value)
    except ValueError:
        return Confidence.MEDIUM


# Conservative stemmer: just enough to unify the variants we actually see (plurals,
# and a few derivational suffixes like ownership->owner), without mangling words.
# Single pass, never iterative — the old iterative s-stripper turned class->cla,
# access->acc, success->succ, status->statu and manufactured collisions. Words ending
# in "ss"/"us"/"is" are left intact, and "-ing"/"-tion" are deliberately NOT handled
# (they over-stem and don't unify the cases we care about; route/routing, auth/
# authentication are a per-decision keywords concern, not a stemmer one).
_DERIVATIONAL_SUFFIXES = ("izations", "ization", "ships", "ship", "ments", "ment")


def _stem(tok: str) -> str:
    for suf in _DERIVATIONAL_SUFFIXES:
        if tok.endswith(suf) and len(tok) - len(suf) >= 4:
            return tok[: -len(suf)]
    if tok.endswith(("ss", "us", "is")):  # class, status, analysis — leave intact
        return tok
    if tok.endswith("ies") and len(tok) > 4:  # categories -> category, policies -> policy
        return tok[:-3] + "y"
    if tok.endswith("es") and len(tok) > 4:
        stem = tok[:-2]
        # sibilant stems take -es (boxes->box, classes->class); others just -s (routes->route)
        return stem if stem.endswith(("s", "x", "z", "ch", "sh")) else tok[:-1]
    if tok.endswith("s") and len(tok) > 3:  # links -> link, owners -> owner
        return tok[:-1]
    return tok


# Identifiers and paths like order_created / db.insertApplication / order-created /
# /blog/write: keep the whole literal as one token (rare -> high idf -> strong
# evidence), not just its split parts. camelCase already survives the splitter (no
# separator); we capture the _ . - / joined forms and normalise every separator to "_"
# so a kebab event name ("order-created") and its code form ("order_created") unify,
# and a route the task names ("/blog/write") matches a decision that references it.
_CODE_LITERAL_RE = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:[-_./][A-Za-z0-9]+)+")
_LITERAL_SEP_RE = re.compile(r"[-./]")


def _code_literals(text: str) -> set[str]:
    return {_LITERAL_SEP_RE.sub("_", m).lower() for m in _CODE_LITERAL_RE.findall(text)}


def _tokens(text: str) -> set[str]:
    # No global synonym table: vocabulary gaps between a task's wording and a
    # decision's wording are bridged per decision by its curated `keywords` field
    # (see _decision_tokens), which scales with the corpus instead of a hand-edited
    # alias list and can't fold unrelated decisions into one another's matches.
    words = set()
    for tok in re.split(r"[^a-z0-9]+", text.lower()):
        if len(tok) >= 3 and tok not in _STOPWORDS:
            words.add(_stem(tok))
    return words | _code_literals(text)


def _decision_tokens(decision: Decision) -> set[str]:
    """The lexical surface a decision can match on: pattern, rationale, and keywords.

    Keywords carry the vocabulary the wording doesn't — the synonyms and code
    identifiers an engineer might type in a task description. They only widen what
    a decision can match; admission still goes through the same evidence floor and
    idf weighting as any other token (a keyword in many decisions is worth ~nothing).
    """
    return _tokens(" ".join([decision.pattern, decision.rationale, *decision.keywords]))


def _build_idf(decisions: list[Decision]) -> dict[str, float]:
    """Inverse document frequency for tokens across the served decisions.

    A token in nearly every decision (boilerplate like "commit"/"shared") gets an idf
    near 0; a rare domain term gets a high idf. Computed over the same set being
    ranked, so it is self-tuning per repo with no hand-maintained stopword list.
    """
    n = len(decisions)
    df: dict[str, int] = {}
    for decision in decisions:
        for tok in _decision_tokens(decision):
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


def _idf_evidence_threshold(idf: dict[str, float]) -> float:
    """idf a single keyword hit must clear to admit an out-of-scope decision on its own.

    A term appearing in only one or two decisions (≈ max idf, minus log 1.5 for the df=2
    case) is rare/domain-specific enough that one hit is real evidence ("webhook",
    "ledger"); a common verb like "write" sits well below it. Self-tuning off the
    corpus's own idf — no hand-set constant, and robust to the skewed idf distribution
    (most tokens are rare, so percentile thresholds collapse to the max).
    """
    if not idf:
        return float("inf")
    return max(idf.values()) - math.log(1.5)


def _clears_evidence_floor(
    hits: set[str], idf: dict[str, float], threshold: float
) -> bool:
    """Whether a decision with no scope relationship has enough lexical evidence.

    Needs several distinct task-keyword overlaps, or one overlap on a rare term —
    so a single common token can't pull off-topic decisions into the result.
    """
    if len(hits) >= _MIN_KEYWORD_HITS:
        return True
    return any(idf.get(tok, 0.0) >= threshold for tok in hits)


def _normalize_scope(scope: str) -> str:
    """Canonical form of a decision scope: a bare path, or ``""`` for global.

    Agents submit scopes in the forms the tool description suggests — a glob
    ("src/services/**"), the literal "global" — as well as plain paths. Trailing
    glob segments add nothing over the directory they qualify ("src/services/**"
    governs the same files the scope "src/services" already covers under prefix
    matching), so they are dropped; a scope that *is* a glob ("**") or the word
    "global" means everywhere, i.e. the empty global scope.
    """
    parts = scope.strip().strip("/").split("/")
    while parts and "*" in parts[-1]:
        parts.pop()
    normalized = "/".join(parts)
    return "" if normalized.lower() == "global" else normalized


def _scope_weight(decision_scope: str, area_paths: list[str]) -> float:
    """Best scope relationship between a decision and any of the queried paths.

    Rewards specificity: an exact or deeper match (the decision is the area, or sits
    *inside* it) outweighs a broad ancestor that merely contains the area, and
    siblings (sharing only a parent dir) score nothing.
    """
    decision_scope = _normalize_scope(decision_scope)
    if decision_scope == "":
        # Global decisions get NO scope credit — applying "everywhere" is not evidence
        # of relevance to *this* task. With scope 0 they fall to the cross-scope tier
        # and must clear the lexical evidence floor, so unrelated doctrine isn't filler.
        return 0.0
    return max((_pair_scope(decision_scope, area) for area in area_paths), default=0.0)


def _pair_scope(decision_scope: str, area: str) -> float:
    scope = decision_scope.strip("/").split("/")
    target = area.strip("/").split("/")
    shared = 0
    for a, b in zip(scope, target):
        if a != b:
            break
        shared += 1
    if shared and shared == len(scope) == len(target):  # exact match — most specific
        return 3.0 + shared
    if shared and shared == len(target):  # decision sits inside the queried area — specific
        return 2.0 + shared
    if shared and shared == len(scope):  # decision is an ancestor of the area
        # Weight by how *close* the ancestor is: a decision scoped src/db is a far
        # better match for src/db/db.ts than one scoped src. Flattening every
        # ancestor to the same weight let generic top-level decisions crowd out the
        # decision whose scope is the file's own directory.
        return float(shared)
    # No root-anchored relationship. Areas are often *names*, not full paths — the
    # tool accepts an architectural area ("billing"), and decisions may be scoped to
    # a layer name rather than a rooted path. If either path appears whole and
    # contiguous inside the other ("billing" in src/billing/webhooks.py), that is a
    # real but weaker relationship: weight it like a far ancestor (segment count of
    # the contained path), below every rooted match of the same depth.
    if _contains(scope, target) or _contains(target, scope):
        return float(min(len(scope), len(target)))
    return 0.0  # siblings/unrelated: no containment either way — not relevant


def _contains(haystack: list[str], needle: list[str]) -> bool:
    """Whether ``needle`` occurs as a contiguous run of segments inside ``haystack``."""
    if not needle or len(needle) >= len(haystack):
        return False
    return any(
        haystack[i : i + len(needle)] == needle
        for i in range(1, len(haystack) - len(needle) + 1)
    )
