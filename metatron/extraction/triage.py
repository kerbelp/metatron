"""The triage judge: an advisory critic pass over candidate priors.

A separate LLM call (independent of extraction — ideally a different/fresh judgment)
scores each candidate as approve / borderline / reject with a one-line reason, to
help a human curate a large queue faster. **It does not change status** — nothing is
auto-promoted; the human still curates. Candidates are batched to limit calls.
"""

from __future__ import annotations

import json
from collections.abc import Callable

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

    def evaluate(
        self,
        priors: list[Prior],
        *,
        on_progress: Callable[[dict], None] | None = None,
    ) -> dict[str, tuple[TriageVerdict, str]]:
        """Return ``{prior_id: (verdict, reason)}`` for the given candidates.

        Candidates are numbered per batch and mapped back by index, so the judge
        never echoes a uuid (which it mangles); a bogus/out-of-range index from
        the judge is ignored rather than fatal.

        Each batch is a (slow) LLM call, so ``on_progress`` — if given — is invoked
        before the run and before each batch with ``{phase, batches_total,
        batches_done, candidates_total, candidates_done}`` (``phase`` is ``start``
        then ``judging``), letting a caller show live progress.
        """
        batches = list(_batches(priors, self._batch_size))
        total_batches = len(batches)

        def report(phase: str, done_batches: int, done_candidates: int) -> None:
            if on_progress is not None:
                on_progress({
                    "phase": phase,
                    "batches_total": total_batches,
                    "batches_done": done_batches,
                    "candidates_total": len(priors),
                    "candidates_done": done_candidates,
                })

        report("start", 0, 0)
        results: dict[str, tuple[TriageVerdict, str]] = {}
        done_candidates = 0
        for batch_index, batch in enumerate(batches):
            report("judging", batch_index, done_candidates)
            prompt = render(self._template, priors=_format_priors(batch))
            for item in _parse_json_array(self._provider.complete(prompt)):
                index = item.get("n")
                if isinstance(index, int) and 1 <= index <= len(batch):
                    prior = batch[index - 1]
                    results[prior.id] = (
                        _parse_verdict(item.get("verdict")),
                        item.get("reason", ""),
                    )
            done_candidates += len(batch)
        return results


def _batches(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _format_priors(priors: list[Prior]) -> str:
    return json.dumps(
        [
            {
                "n": i,  # 1-based index within this batch; map back locally
                "pattern": p.pattern,
                "scope": p.scope,
                "rationale": p.rationale,
                "confidence": p.confidence.value,
            }
            for i, p in enumerate(priors, start=1)
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
