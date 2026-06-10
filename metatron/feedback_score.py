"""Aggregate per-decision helpfulness from agent ratings.

Agents rate served decisions 1-10 in ``submit_feedback`` (stored on each FEEDBACK
event's ``ratings`` map). This module folds every rating a decision has ever received
into a single **helpfulness score** that two consumers share:

- the serve path, which uses it to auto-weight ranking *within* a relevance tier
  (see :func:`metatron.mcp_server.service.get_decisions_for_context`), and
- the curation UI's leaderboard, which surfaces helpful vs. misleading decisions.

The aggregate is deliberately conservative so the loop can't be jerked around:

- **Time decay** — a rating's weight halves every ``HALF_LIFE_DAYS``, so the score
  tracks recent experience and stale verdicts fade.
- **Shrinkage toward neutral** — a Bayesian pseudo-count pulls decisions with few
  ratings back toward ``NEUTRAL``, so one rave can't crown a decision and one pan can't
  bury it; only a *sustained* pattern moves the score.
- **Corpus-relative centering** — the ranking signal measures distance from the
  corpus's own typical rating, not the scale midpoint, because model raters skew
  positive and would otherwise read as praising everything.

This module is pure: it never reads or writes the store. It only ever *describes*
helpfulness — promotion/demotion across the canonical set stays human-gated.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import datetime, timezone

from metatron.events import Event, EventKind

# A rating's weight halves every this many days. 90d ≈ "this quarter's experience".
HALF_LIFE_DAYS = 90.0
# The score a decision reverts to with no (or very few) ratings: the midpoint of 1..10.
NEUTRAL = 5.5
# Pseudo-count of neutral ratings mixed in. Higher = more ratings needed to move the
# score off neutral. 3 means a decision needs several consistent ratings to shift.
PSEUDO_COUNT = 3.0
# The score range either side of NEUTRAL, used to normalise into a [-1, 1] signal.
_HALF_RANGE = 4.5
# Synthetic ratings for binary-only feedback (helpful/unhelpful lists with no graded
# ``ratings`` map). Mirror of the derivation in ``submit_feedback`` (≥7 → helpful,
# ≤4 → noise): one representative score from each band, so cheap binary feedback
# still feeds serve ordering instead of counting only toward UI tallies.
BINARY_HELPFUL_RATING = 8
BINARY_UNHELPFUL_RATING = 3


@dataclass(frozen=True)
class HelpfulnessScore:
    """One decision's aggregate helpfulness.

    ``score`` is on the 1-10 rating scale (shrunk toward :data:`NEUTRAL`);
    ``n_ratings`` is the raw count of ratings it is built from (for "trust" display
    and review-queue thresholds); ``baseline`` is the corpus's typical rating — the
    zero point ``centered`` measures against.
    """

    score: float
    n_ratings: int
    baseline: float = NEUTRAL

    @property
    def centered(self) -> float:
        """Score relative to the corpus baseline, clamped to [-1, 1] (the ranking signal).

        Model raters skew positive — most ratings land 7-9 — so distance from the
        scale midpoint would mark nearly every decision "helpful" and compress the
        ordering signal. Measured against the corpus's own (decayed, shrunk) mean
        rating instead, this reads "better/worse than this repo's typical decision".
        """
        raw = (self.score - self.baseline) / _HALF_RANGE
        return max(-1.0, min(1.0, raw))


def _event_ratings(event: Event) -> dict[str, int]:
    """The graded ratings an event contributes, synthesized from binary lists if needed.

    Graded ``ratings`` take precedence: when present, the binary lists were derived
    *from* them at capture, so counting both would double-count. Only a binary-only
    event gets synthetic scores (helpful wins if an id somehow appears in both lists).
    """
    if event.ratings:
        return event.ratings
    synthetic = {pid: BINARY_UNHELPFUL_RATING for pid in event.unhelpful_decision_ids}
    synthetic.update({pid: BINARY_HELPFUL_RATING for pid in event.helpful_decision_ids})
    return synthetic


def _ratings_events(events: Iterable[Event]) -> Iterator[tuple[Event, dict[str, int]]]:
    for event in events:
        if event.kind is not EventKind.FEEDBACK:
            continue
        ratings = _event_ratings(event)
        if ratings:
            yield event, ratings


def _age_days(ts: datetime, now: datetime) -> float:
    age = (now - ts).total_seconds() / 86400.0
    return max(age, 0.0)  # a clock-skewed future rating still counts as "now"


def helpfulness_scores(
    events: Iterable[Event], *, now: datetime | None = None
) -> dict[str, HelpfulnessScore]:
    """Aggregate ratings across feedback events into a score per decision id.

    ``events`` is any iterable of events (non-feedback and unrated events are
    ignored; binary-only feedback contributes synthetic ratings). Returns only
    decisions that have at least one rating. ``now`` defaults to the current UTC
    time and is injectable for deterministic tests.
    """
    now = now or datetime.now(timezone.utc)
    weighted_sum: dict[str, float] = {}
    weight_total: dict[str, float] = {}
    counts: dict[str, int] = {}

    for event, ratings in _ratings_events(events):
        w = 0.5 ** (_age_days(event.timestamp, now) / HALF_LIFE_DAYS)
        for decision_id, raw in ratings.items():
            weighted_sum[decision_id] = weighted_sum.get(decision_id, 0.0) + w * raw
            weight_total[decision_id] = weight_total.get(decision_id, 0.0) + w
            counts[decision_id] = counts.get(decision_id, 0) + 1

    # Corpus baseline, leave-one-out: each decision is centered against the decayed,
    # shrunk mean rating of the *other* decisions — its own ratings never move its
    # own zero point. With sparse data (or a lone rated decision) the baseline
    # degrades gracefully to NEUTRAL, restoring midpoint centering.
    all_sum = sum(weighted_sum.values())
    all_weight = sum(weight_total.values())

    scores: dict[str, HelpfulnessScore] = {}
    for decision_id, total_w in weight_total.items():
        score = (weighted_sum[decision_id] + PSEUDO_COUNT * NEUTRAL) / (total_w + PSEUDO_COUNT)
        baseline = (all_sum - weighted_sum[decision_id] + PSEUDO_COUNT * NEUTRAL) / (
            all_weight - total_w + PSEUDO_COUNT
        )
        scores[decision_id] = HelpfulnessScore(
            score=score, n_ratings=counts[decision_id], baseline=baseline
        )
    return scores
