"""Turn per-scope signals into candidate priors via an LLM provider.

This is the LLM half of extraction. It renders the editable prompt from a
``ScopeSignals`` bundle, asks the provider for structured JSON, and validates the
result into ``Prior`` records. Every prior produced here is a ``candidate`` of
``bootstrap`` origin — bootstrapping never promotes anything to canonical.
"""

from __future__ import annotations

import json

from metatron.extraction.prompts import load_prompt, render
from metatron.extraction.provider import LLMProvider
from metatron.extraction.signals import ScopeSignals
from metatron.models import Confidence, Origin, Prior, SourceRef, SourceRefKind


class ExtractionError(Exception):
    """Raised when an LLM response cannot be parsed into priors."""


class PriorExtractor:
    def __init__(
        self,
        provider: LLMProvider,
        repo: str,
        model: str = "",
        template: str | None = None,
    ) -> None:
        self._provider = provider
        self._repo = repo
        self._model = model
        self._template = template if template is not None else load_prompt(
            "extract_priors"
        )

    def extract(self, signals: ScopeSignals) -> list[Prior]:
        prompt = render(
            self._template,
            scope=signals.scope,
            signals=_format_signals(signals),
        )
        raw = self._provider.complete(prompt)
        return [self._to_prior(item, signals) for item in _parse_json_array(raw)]

    def _to_prior(self, item: dict, signals: ScopeSignals) -> Prior:
        if "pattern" not in item:
            raise ExtractionError(f"prior missing 'pattern': {item!r}")
        return Prior(
            repo=self._repo,
            pattern=item["pattern"],
            scope=item.get("scope") or signals.scope,
            rationale=item.get("rationale", ""),
            confidence=_parse_confidence(item.get("confidence")),
            model=self._model,
            origin=Origin.BOOTSTRAP,
            source_refs=[
                SourceRef(
                    kind=SourceRefKind.FILE,
                    ref=signals.scope,
                    detail=(
                        f"bootstrapped from {signals.file_count} files, "
                        f"{signals.commit_count} commits"
                    ),
                )
            ],
        )


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
        raise ExtractionError(f"response was not valid JSON: {exc}") from exc
    if not isinstance(data, list):
        raise ExtractionError(f"expected a JSON array, got {type(data).__name__}")
    return data


def _strip_code_fence(text: str) -> str:
    if not text.startswith("```"):
        return text
    # Drop the opening fence line (``` or ```json) and any trailing fence.
    body = text.split("\n", 1)[1] if "\n" in text else ""
    if body.rstrip().endswith("```"):
        body = body.rstrip()[:-3]
    return body.strip()


def _format_signals(signals: ScopeSignals) -> str:
    def counts(items) -> str:
        return ", ".join(f"{c.name}({c.count})" for c in items) or "(none)"

    lines = [
        f"files: {signals.file_count}",
        f"recurring imports: {counts(signals.imports)}",
        f"recurring decorators: {counts(signals.decorators)}",
        f"recurring base classes: {counts(signals.bases)}",
        (
            f"commits touching this scope: {signals.commit_count} "
            f"(fixes: {signals.fix_count}, reverts: {signals.revert_count})"
        ),
    ]
    if signals.subjects:
        lines.append("recent commit subjects (newest first):")
        lines.extend(f"  - {s}" for s in signals.subjects)
    return "\n".join(lines)
