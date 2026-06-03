"""Tests for the per-prior helpfulness aggregate (time decay + shrinkage)."""

from datetime import datetime, timedelta, timezone

from metatron.events import Event, EventKind
from metatron.feedback_score import (
    HALF_LIFE_DAYS,
    NEUTRAL,
    HelpfulnessScore,
    helpfulness_scores,
)

NOW = datetime(2026, 6, 3, tzinfo=timezone.utc)


def _fb(ratings, *, days_ago=0):
    return Event(
        repo="r", kind=EventKind.FEEDBACK, ratings=ratings,
        timestamp=NOW - timedelta(days=days_ago),
    )


def test_no_events_yields_no_scores():
    assert helpfulness_scores([], now=NOW) == {}


def test_non_feedback_and_unrated_events_are_ignored():
    events = [
        Event(repo="r", kind=EventKind.QUERY, prior_ids=["p1"], timestamp=NOW),
        _fb({}),  # feedback but no ratings
    ]
    assert helpfulness_scores(events, now=NOW) == {}


def test_single_rating_is_shrunk_toward_neutral():
    # one perfect 10, fresh: score is pulled below 10 toward NEUTRAL, not all the way.
    scores = helpfulness_scores([_fb({"p1": 10})], now=NOW)
    s = scores["p1"]
    assert isinstance(s, HelpfulnessScore)
    assert s.n_ratings == 1
    assert NEUTRAL < s.score < 10
    # with pseudo-count 3 and weight 1: (10 + 3*5.5)/(1+3) = 6.625
    assert round(s.score, 3) == 6.625


def test_more_consistent_ratings_move_the_score_closer_to_the_signal():
    few = helpfulness_scores([_fb({"p1": 10})], now=NOW)["p1"].score
    many = helpfulness_scores([_fb({"p1": 10}) for _ in range(20)], now=NOW)["p1"].score
    assert many > few  # sustained praise pushes harder than a single rating
    assert many < 10    # but never reaches the raw ceiling


def test_a_lone_low_rating_cannot_bury_a_prior():
    # a single 1 stays well above the floor thanks to shrinkage.
    s = helpfulness_scores([_fb({"p1": 1})], now=NOW)["p1"].score
    assert s < NEUTRAL
    assert round(s, 3) == 4.375  # (1 + 3*5.5)/(1+3)


def test_time_decay_lets_recent_ratings_dominate_stale_ones():
    # an old pan (1) two half-lives back vs a fresh rave (10): fresh wins.
    events = [
        _fb({"p1": 1}, days_ago=int(HALF_LIFE_DAYS * 2)),
        _fb({"p1": 10}, days_ago=0),
    ]
    s = helpfulness_scores(events, now=NOW)["p1"].score
    assert s > NEUTRAL  # recency tips it positive despite the old negative
    assert helpfulness_scores(events, now=NOW)["p1"].n_ratings == 2


def test_centered_signal_is_bounded_and_signed():
    pos = HelpfulnessScore(score=10.0, n_ratings=5).centered
    neg = HelpfulnessScore(score=1.0, n_ratings=5).centered
    assert 0 < pos <= 1.0
    assert -1.0 <= neg < 0
    assert HelpfulnessScore(score=NEUTRAL, n_ratings=0).centered == 0.0


def test_scores_are_independent_per_prior():
    scores = helpfulness_scores([_fb({"p1": 9, "p2": 2})], now=NOW)
    assert scores["p1"].score > NEUTRAL > scores["p2"].score
