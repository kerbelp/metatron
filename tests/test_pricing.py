"""Tests for token-cost estimation."""

from metatron.pricing import estimate_cost


def test_known_model_costs_input_and_output():
    # 1M input @ $15 + 1M output @ $75 = $90
    assert estimate_cost("claude-opus-4-8", 1_000_000, 1_000_000) == 90.0


def test_partial_tokens():
    # 100k in @ $3, 50k out @ $15 = 0.3 + 0.75 = 1.05
    assert round(estimate_cost("claude-sonnet-4-6", 100_000, 50_000), 4) == 1.05


def test_unknown_model_returns_none():
    assert estimate_cost("mystery-model", 1000, 1000) is None
