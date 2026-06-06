"""Reshape raw agent feedback ("what was missing") into structured candidate decisions.

This is the LLM half of feedback refinement — the counterpart to the bootstrap
extractor, but sourced from human/agent feedback rather than code signals. A single
gap report often bundles several conventions, so the model is asked to split them.
Every decision produced is a ``candidate`` of ``agent_feedback`` origin — refinement
never promotes anything to canonical; a human still curates.
"""

from __future__ import annotations

import json

from metatron.extraction.prompts import load_prompt, render
from metatron.extraction.provider import LLMProvider
from metatron.models import Confidence, Origin, Decision


class RefineError(Exception):
    """Raised when a refiner response cannot be parsed into decisions."""


class FeedbackRefiner:
    def __init__(
        self,
        provider: LLMProvider,
        repo: str = "",
        model: str = "",
        template: str | None = None,
    ) -> None:
        self._provider = provider
        self._repo = repo
        self._model = model
        self._template = template if template is not None else load_prompt(
            "refine_feedback"
        )

    @property
    def provider(self) -> LLMProvider:
        """The underlying LLM provider (so callers can read token usage for cost)."""
        return self._provider

    def refine(self, gap_text: str, scope_hint: str = "", task: str = "") -> list[Decision]:
        prompt = render(
            self._template,
            gap=gap_text,
            scope=scope_hint or "(unspecified)",
            task=task or "(unspecified)",
        )
        raw = self._provider.complete(prompt)
        decisions: list[Decision] = []
        for item in _parse_json_array(raw):
            pattern = (item.get("pattern") or "").strip()
            if not pattern:
                continue  # skip empties rather than fabricate
            decisions.append(
                Decision(
                    repo=self._repo,
                    pattern=pattern,
                    scope=(item.get("scope") or scope_hint or "").strip(),
                    rationale=(item.get("rationale") or "").strip(),
                    confidence=_parse_confidence(item.get("confidence")),
                    model=self._model,
                    origin=Origin.AGENT_FEEDBACK,
                )
            )
        return decisions


def _parse_confidence(value: object) -> Confidence:
    try:
        return Confidence(value)
    except ValueError:
        return Confidence.MEDIUM


def _parse_json_array(raw: str) -> list:
    text = _strip_code_fence(raw.strip())
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RefineError(f"refiner response was not valid JSON: {exc}") from exc
    if not isinstance(data, list):
        raise RefineError(f"expected a JSON array, got {type(data).__name__}")
    return data


def _strip_code_fence(text: str) -> str:
    if not text.startswith("```"):
        return text
    body = text.split("\n", 1)[1] if "\n" in text else ""
    if body.rstrip().endswith("```"):
        body = body.rstrip()[:-3]
    return body.strip()
