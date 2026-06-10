"""The keyword enricher: a batched LLM pass that backfills retrieval keywords.

Decisions created before keyword-aware extraction (or whose extraction omitted the
field) match only on their pattern/rationale wording. This pass asks an LLM for the
synonyms and code identifiers an engineer might use in a task description, so older
corpora gain the same retrievability as newly extracted decisions. **It never touches
status** — it only fills the ``keywords`` field; curation stays human-gated.
"""

from __future__ import annotations

import json
from collections.abc import Callable

from metatron.extraction.prompts import load_prompt, render
from metatron.extraction.provider import LLMProvider
from metatron.models import Decision, sanitize_keywords


class EnrichError(Exception):
    """Raised when an enricher response cannot be parsed."""


class KeywordEnricher:
    def __init__(
        self,
        provider: LLMProvider,
        template: str | None = None,
        batch_size: int = 15,
    ) -> None:
        self._provider = provider
        self._template = template if template is not None else load_prompt(
            "enrich_keywords"
        )
        self._batch_size = max(1, batch_size)

    def enrich(
        self,
        decisions: list[Decision],
        *,
        on_progress: Callable[[dict], None] | None = None,
    ) -> dict[str, list[str]]:
        """Return ``{decision_id: keywords}`` for the given decisions.

        Decisions are numbered per batch and mapped back by index, so the model
        never echoes a uuid (which it mangles); a bogus/out-of-range index is
        ignored rather than fatal, and keywords are sanitized like every other
        intake path. ``on_progress`` — if given — is invoked before the run and
        before each (slow) batch call with ``{phase, batches_total, batches_done,
        decisions_total, decisions_done}`` (``phase`` is ``start`` then
        ``enriching``).
        """
        batches = list(_batches(decisions, self._batch_size))

        def report(phase: str, done_batches: int, done_decisions: int) -> None:
            if on_progress is not None:
                on_progress({
                    "phase": phase,
                    "batches_total": len(batches),
                    "batches_done": done_batches,
                    "decisions_total": len(decisions),
                    "decisions_done": done_decisions,
                })

        report("start", 0, 0)
        results: dict[str, list[str]] = {}
        done = 0
        for batch_index, batch in enumerate(batches):
            report("enriching", batch_index, done)
            prompt = render(self._template, decisions=_format_decisions(batch))
            for item in _parse_json_array(self._provider.complete(prompt)):
                index = item.get("n")
                keywords = sanitize_keywords(item.get("keywords"))
                if isinstance(index, int) and 1 <= index <= len(batch) and keywords:
                    results[batch[index - 1].id] = keywords
            done += len(batch)
        return results


def _batches(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _format_decisions(decisions: list[Decision]) -> str:
    return json.dumps(
        [
            {
                "n": i,  # 1-based index within this batch; map back locally
                "pattern": p.pattern,
                "scope": p.scope,
                "rationale": p.rationale,
            }
            for i, p in enumerate(decisions, start=1)
        ],
        indent=2,
    )


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
        raise EnrichError(f"enricher response was not valid JSON: {exc}") from exc
    if not isinstance(data, list):
        raise EnrichError(f"expected a JSON array, got {type(data).__name__}")
    return data
