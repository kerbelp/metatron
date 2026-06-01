"""Approximate token-cost estimation.

Rates are **approximate published USD per 1M tokens** (input, output) and may be
out of date — confirm against your Anthropic plan. Tokens themselves are measured;
the dollar figure is tokens × these rates, and should be treated as an estimate.
"""

from __future__ import annotations

# (input $/Mtok, output $/Mtok) — approximate; override as your pricing dictates.
PRICES_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-opus-4-8": (15.0, 75.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
}


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float | None:
    """Estimated USD for a run, or ``None`` if the model's rate is unknown."""
    rate = PRICES_PER_MTOK.get(model)
    if rate is None:
        return None
    rate_in, rate_out = rate
    return (input_tokens / 1e6) * rate_in + (output_tokens / 1e6) * rate_out
