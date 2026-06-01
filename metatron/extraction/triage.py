"""The triage judge: an advisory critic pass over candidate priors.

A separate LLM call (independent of extraction — ideally a different/fresh judgment)
scores each candidate as approve / borderline / reject with a one-line reason, to
help a human curate a large queue faster. **It does not change status** — nothing is
auto-promoted; the human still curates. Candidates are batched to limit calls.
"""

from __future__ import annotations

import json

from metatron.extraction.prompts import load_prompt, render
from metatron.extraction.provider import LLMProvider
from metatron.models import Prior, TriageVerdict

_VERDICTS = {
    "approve": TriageVerdict.APPROVE,
    "borderline": TriageVerdict.BORDERLINE,
    "reject": TriageVerdict.REJECT,
}


class TriageError(Exception):
    """Raised when a judge response cannot be parsed."""


class PriorJudge:
    def __init__(
        self,
        provider: LLMProvider,
        template: str | None = None,
        batch_size: int = 15,
    ) -> None:
        self._provider = provider
        self._template = template if template is not None else load_prompt(
            "triage_priors"
        )
        self._batch_size = max(1, batch_size)

    def evaluate(self, priors: list[Prior]) -> dict[str, tuple[TriageVerdict, str]]:
        """Return ``{prior_id: (verdict, reason)}`` for the given candidates."""
        results: dict[str, tuple[TriageVerdict, str]] = {}
        for batch in _batches(priors, self._batch_size):
            prompt = render(self._template, priors=_format_priors(batch))
            for item in _parse_json_array(self._provider.complete(prompt)):
                prior_id = item.get("id")
                if prior_id:
                    results[prior_id] = (
                        _parse_verdict(item.get("verdict")),
                        item.get("reason", ""),
                    )
        return results


def _batches(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _format_priors(priors: list[Prior]) -> str:
    return json.dumps(
        [
            {
                "id": p.id,
                "pattern": p.pattern,
                "scope": p.scope,
                "rationale": p.rationale,
                "confidence": p.confidence.value,
            }
            for p in priors
        ],
        indent=2,
    )


def _parse_verdict(value: object) -> TriageVerdict:
    return _VERDICTS.get(value, TriageVerdict.BORDERLINE) if isinstance(value, str) else TriageVerdict.BORDERLINE


def _parse_json_array(raw: str) -> list:
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
        text = text.strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise TriageError(f"judge response was not valid JSON: {exc}") from exc
    if not isinstance(data, list):
        raise TriageError(f"expected a JSON array, got {type(data).__name__}")
    return data
