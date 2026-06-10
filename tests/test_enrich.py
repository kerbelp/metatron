"""The keyword enricher: a batched LLM pass that backfills retrieval keywords.

Like triage, it never touches status — it only fills the keywords field on
decisions that predate keyword-aware extraction.
"""

import json

from metatron.extraction.enrich import KeywordEnricher
from metatron.extraction.provider import LLMProvider
from metatron.models import Origin, Decision


class FakeProvider(LLMProvider):
    def __init__(self, response: str) -> None:
        self.response = response
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.response


def _decision(pattern: str) -> Decision:
    return Decision(repo="r", pattern=pattern, scope="s", rationale="x",
                    origin=Origin.BOOTSTRAP)


def test_enricher_maps_indices_back_to_decision_ids():
    a, b = _decision("A"), _decision("B")
    resp = json.dumps([
        {"n": 1, "keywords": ["sqlite", "persistence"]},
        {"n": 2, "keywords": ["webhook"]},
    ])
    results = KeywordEnricher(FakeProvider(resp)).enrich([a, b])
    assert results == {a.id: ["sqlite", "persistence"], b.id: ["webhook"]}


def test_enricher_sanitizes_and_ignores_bogus_indices():
    a = _decision("A")
    resp = json.dumps([
        {"n": 1, "keywords": ["  s3 ", "s3", "", 7]},
        {"n": 99, "keywords": ["ghost"]},
        {"n": "x", "keywords": ["ghost"]},
    ])
    results = KeywordEnricher(FakeProvider(resp)).enrich([a])
    assert results == {a.id: ["s3"]}


def test_enricher_batches_decisions():
    decisions = [_decision(f"p{i}") for i in range(5)]
    provider = FakeProvider("[]")
    KeywordEnricher(provider, batch_size=2).enrich(decisions)
    assert len(provider.prompts) == 3  # 2 + 2 + 1


def test_enricher_handles_fenced_json():
    a = _decision("A")
    resp = "```json\n" + json.dumps([{"n": 1, "keywords": ["acl"]}]) + "\n```"
    results = KeywordEnricher(FakeProvider(resp)).enrich([a])
    assert results == {a.id: ["acl"]}
