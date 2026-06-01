"""Tests for the triage judge (advisory scoring of candidate priors)."""

import json
import re

import pytest

from metatron.extraction.provider import LLMProvider
from metatron.extraction.triage import PriorJudge, TriageError
from metatron.models import Origin, Prior, TriageVerdict


class IdAwareJudge(LLMProvider):
    """Returns the given verdict for every prior id it sees in the prompt."""

    def __init__(self, verdict: str = "approve") -> None:
        self.verdict = verdict
        self.calls = 0

    def complete(self, prompt: str) -> str:
        self.calls += 1
        ids = re.findall(r'"id":\s*"([^"]+)"', prompt)
        return json.dumps([{"id": i, "verdict": self.verdict, "reason": "because"} for i in ids])


class StaticJudge(LLMProvider):
    def __init__(self, response: str) -> None:
        self.response = response

    def complete(self, prompt: str) -> str:
        return self.response


def _prior(pid: str) -> Prior:
    return Prior(id=pid, repo="r", pattern=f"pattern {pid}", scope="app", rationale="why", origin=Origin.BOOTSTRAP)


def test_evaluate_returns_a_verdict_and_reason_per_prior():
    priors = [_prior("a"), _prior("b")]
    result = PriorJudge(IdAwareJudge("approve")).evaluate(priors)
    assert set(result) == {"a", "b"}
    assert result["a"] == (TriageVerdict.APPROVE, "because")


def test_batches_candidates_to_limit_calls():
    judge = IdAwareJudge()
    PriorJudge(judge, batch_size=2).evaluate([_prior(str(i)) for i in range(5)])
    assert judge.calls == 3  # ceil(5/2)


def test_unknown_verdict_defaults_to_borderline():
    resp = json.dumps([{"id": "a", "verdict": "huh", "reason": "x"}])
    result = PriorJudge(StaticJudge(resp)).evaluate([_prior("a")])
    assert result["a"][0] is TriageVerdict.BORDERLINE


def test_handles_markdown_fenced_json():
    resp = "```json\n" + json.dumps([{"id": "a", "verdict": "reject", "reason": "vague"}]) + "\n```"
    result = PriorJudge(StaticJudge(resp)).evaluate([_prior("a")])
    assert result["a"][0] is TriageVerdict.REJECT


def test_malformed_json_raises():
    with pytest.raises(TriageError):
        PriorJudge(StaticJudge("not json")).evaluate([_prior("a")])
