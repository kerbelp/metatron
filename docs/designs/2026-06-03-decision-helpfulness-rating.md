# Design: decision helpfulness rating → auto-weighted ranking

- **Date:** 2026-06-03
- **Status:** approved
- **Maps to:** `docs/future-features.md` item **C** (self-improving loop). This
  builds the **first, bounded slice** of C — see Scope & the line we hold.

## Goal

Let coding agents rate each served decision **1–10** for how helpful it actually was,
then use those ratings to **automatically reorder which canonical decisions get served
first** — so genuinely helpful decisions rise and misleading ones sink over time — and
to surface a **leaderboard** that doubles as a human-curation queue for the decisions
the data says are hurting.

This extends item **B** (binary helpful/unhelpful capture, already shipped) into a
graded signal, and turns on a **bounded** version of item **C**'s automatic
actuation.

## Scope & the line we hold

This is item **C**, previously deferred. The owner has decided to turn it on. We do
so in a deliberately bounded way that preserves the project's core invariant:

- **No decision self-promotes.** Ratings never promote a candidate to canonical, never
  un-reject, and never auto-demote a decision *out* of canonical. Crossing the canonical
  boundary stays 100% human-gated.
- **Auto-weighting only reorders *within* a scope tier.** Helpfulness adjusts the
  serve-time *order* among already-canonical decisions that are already equally relevant
  by scope. It can push a misleading decision below the serve `limit` (so it stops being
  served) — but the decision still exists and removing it stays a human action.
- **"Helpful here ≠ better everywhere"** (the caution in `future-features.md` B): we
  aggregate a *global* per-decision score but apply it as a **bounded** term that only
  breaks ties *within a relevance tier*. A globally-loved decision can win among equally
  relevant peers; it can never jump the scope/keyword relevance gate to crowd out a
  more relevant decision. This is the structural mitigation for that caution.
- **No eval harness (item A) yet.** C's stated prerequisite is a trustworthy quality
  metric. We proceed without it as an accepted, owner-approved risk, mitigated by (a)
  the within-tier bound above, (b) time decay so bad early ratings fade, (c)
  shrinkage so a handful of ratings can't swing a decision, and (d) the leaderboard's
  human review queue for low-scoring decisions.

`CLAUDE.md` is updated to record that Metatron now has a **partial self-learning
loop**: usage ratings auto-weight serve ordering among canonical decisions, while every
mutation across the canonical boundary remains human-gated.

## Capture & storage

- **Wire format stays index-based.** `submit_feedback` gains `ratings: {index: score}`
  (keys are 1-based indices into the named query's served decisions; scores 1–10).
  Agents never echo UUIDs — the service resolves indices → decision ids locally with the
  existing query-id map, exactly as `helpful`/`unhelpful` already work. Out-of-range
  indices and out-of-band scores (outside 1–10) are dropped.
- **Event model:** add `ratings: dict[str, int]` to `Event`, stored keyed by
  **decision_id** (the resolved form). Persisted as a new JSON column `ratings` on the
  `events` table via the existing `_ensure_column` additive migration; defaults to
  `{}` so no backfill is needed.
- **Back-compat:** when an agent sends `ratings` but omits `helpful`/`unhelpful`, the
  service derives them (score ≥ 7 → helpful, ≤ 4 → unhelpful) so the existing
  Feedback tallies/analytics keep working unchanged. Explicit binary lists are still
  accepted and take precedence when provided.

## Scoring model

New pure module `metatron/feedback_score.py`, unit-tested in isolation. Given a
repo's FEEDBACK events, it produces `{decision_id: HelpfulnessScore}` where
`HelpfulnessScore = (score: float, n_ratings: int)`:

- **Time decay** — each rating is weighted `w = 0.5 ** (age_days / HALF_LIFE)`,
  `HALF_LIFE = 90` days. Recent ratings dominate; stale ones fade. This is the
  "adjust with time" behaviour.
- **Shrinkage toward neutral** — `score = (Σ wᵢ·rᵢ + k·NEUTRAL) / (Σ wᵢ + k)` with
  `NEUTRAL = 5.5` and pseudo-count `k = 3`. One rave can't crown a decision and one pan
  can't tank it; a *sustained* pattern moves the score.
- Output reused by both the serve path (ranking) and the UI (leaderboard) — one
  source of truth for "how helpful is this decision."

Tuning knobs (`HALF_LIFE`, `k`, `NEUTRAL`) live as named module constants.

## Ranking integration

- `get_decisions_for_context` gains an optional `helpfulness: dict[str, float]` argument
  (decision_id → centered score). The service stays pure and testable; the **MCP server**
  builds the map from the event store and passes it in.
- The within-tier sort key gains a **bounded** term:
  `+ H_SCALE * (score − 5.5) / 4.5`, range `±H_SCALE` with `H_SCALE = 2.0`
  (comparable to a couple of keyword-idf hits).
- **Guardrail (enforced by construction):** tiers (on-scope-topical → cross-scope-
  topical → on-scope-generic) are still filled in priority order; helpfulness only
  reorders entries *inside* a tier. It cannot move a decision across tiers, so it can
  never override the scope/keyword relevance gate.

## UI — Leaderboard

- New **Leaderboard** nav tab (alongside Usage / Quality / Feedback), repo-scoped
  like every other screen, backed by a new `api.leaderboard(store, event_store, repo)`.
- Two ranked lists over canonical decisions:
  - **Most helpful** — highest scores (the decisions carrying their weight).
  - **Misleading / review** — lowest scores among decisions with enough ratings to
    trust; each row carries the existing **Reject / Edit** actions, so the leaderboard
    is also the human-curation queue for decisions the data says are hurting.
- Each row: pattern, scope, score (1–10), rating count, and the ranking effect
  (▲ boosted / ▼ demoted). Action-item count banner consistent with the other
  screens (`N decisions flagged for review`).

## Agent guidance

- `submit_feedback`'s tool docstring asks agents to rate each served decision 1–10 by
  its `[index]` in `ratings`, in addition to the existing what-was-missing report.
- The onboarding / Stop-hook nudge that already promotes `submit_feedback` is updated
  to mention the rating.

## Testing

- `feedback_score`: decay ordering, shrinkage with low n, neutral default, empty
  input — pure unit tests.
- Capture: index→id resolution, score clamping, derived binary, migration round-trip.
- Ranking: a higher-rated peer outranks a lower-rated peer *within* a tier; a loved
  off-scope decision still cannot jump a scope tier.
- UI: leaderboard markup present; `api.leaderboard` returns the two lists with scores.

## Non-goals

- No auto-promotion / auto-demotion / auto-reject across the canonical boundary.
- No eval harness (item A) — still deferred.
- No change to extraction or to confidence (helpfulness is its own signal, never
  overloaded onto `confidence`).
