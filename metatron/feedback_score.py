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

This module is pure: it never reads or writes the store. It only ever *describes*
helpfulness — promotion/demotion across the canonical set stays human-gated.
"""

from __future__ import annotations

from collections.abc import Iterable
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


@dataclass(frozen=True)
class HelpfulnessScore:
    """One decision's aggregate helpfulness.

    ``score`` is on the 1-10 rating scale (shrunk toward :data:`NEUTRAL`);
    ``n_ratings`` is the raw count of ratings it is built from (for "trust" display
    and review-queue thresholds).
    """

    score: float
    n_ratings: int

    @property
    def centered(self) -> float:
        """Score relative to neutral in roughly [-1, 1] (the ranking signal)."""
        return (self.score - NEUTRAL) / _HALF_RANGE


def _ratings_events(events: Iterable[Event]) -> Iterable[Event]:
    return (e for e in events if e.kind is EventKind.FEEDBACK and e.ratings)


def _age_days(ts: datetime, now: datetime) -> float:
    age = (now - ts).total_seconds() / 86400.0
    return max(age, 0.0)  # a clock-skewed future rating still counts as "now"


def helpfulness_scores(
    events: Iterable[Event], *, now: datetime | None = None
) -> dict[str, HelpfulnessScore]:
    """Aggregate ratings across feedback events into a score per decision id.

    ``events`` is any iterable of events (non-feedback and unrated events are
    ignored). Returns only decisions that have at least one rating. ``now`` defaults to
    the current UTC time and is injectable for deterministic tests.
    """
    now = now or datetime.now(timezone.utc)
    weighted_sum: dict[str, float] = {}
    weight_total: dict[str, float] = {}
    counts: dict[str, int] = {}

    for event in _ratings_events(events):
        w = 0.5 ** (_age_days(event.timestamp, now) / HALF_LIFE_DAYS)
        for decision_id, raw in event.ratings.items():
            weighted_sum[decision_id] = weighted_sum.get(decision_id, 0.0) + w * raw
            weight_total[decision_id] = weight_total.get(decision_id, 0.0) + w
            counts[decision_id] = counts.get(decision_id, 0) + 1

    scores: dict[str, HelpfulnessScore] = {}
    for decision_id, total_w in weight_total.items():
        score = (weighted_sum[decision_id] + PSEUDO_COUNT * NEUTRAL) / (total_w + PSEUDO_COUNT)
        scores[decision_id] = HelpfulnessScore(score=score, n_ratings=counts[decision_id])
    return scores
