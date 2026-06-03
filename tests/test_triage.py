"""Tests for the triage judge (advisory scoring of candidate priors).

Candidates are presented to the judge with a small integer index (``n``) and
mapped back locally — the judge never has to echo a uuid, which it gets wrong.
"""

import json
import re

import pytest

from metatron.extraction.provider import LLMProvider
from metatron.extraction.triage import PriorJudge, TriageError
from metatron.models import Origin, Prior, TriageVerdict


class IndexJudge(LLMProvider):
    """Returns the given verdict for every candidate index it sees in the prompt."""

    def __init__(self, verdict: str = "approve") -> None:
        self.verdict = verdict
        self.calls = 0

    def complete(self, prompt: str) -> str:
        self.calls += 1
        ns = [int(n) for n in re.findall(r'"n":\s*(\d+)', prompt)]
        return json.dumps([{"n": n, "verdict": self.verdict, "reason": "because"} for n in ns])


class StaticJudge(LLMProvider):
    def __init__(self, response: str) -> None:
        self.response = response

    def complete(self, prompt: str) -> str:
        return self.response


def _prior(pid: str) -> Prior:
    return Prior(id=pid, repo="r", pattern=f"pattern {pid}", scope="app", rationale="why", origin=Origin.BOOTSTRAP)


def test_evaluate_returns_a_verdict_and_reason_per_prior():
    priors = [_prior("aaaa"), _prior("bbbb")]
    result = PriorJudge(IndexJudge("approve")).evaluate(priors)
    assert set(result) == {"aaaa", "bbbb"}
    assert result["aaaa"] == (TriageVerdict.APPROVE, "because")


def test_batches_candidates_to_limit_calls():
    judge = IndexJudge()
    PriorJudge(judge, batch_size=2).evaluate([_prior(str(i)) for i in range(5)])
    assert judge.calls == 3  # ceil(5/2)


def test_evaluate_reports_progress_per_batch():
    seen: list[dict] = []
    priors = [_prior(str(i)) for i in range(5)]  # batch_size 2 -> 3 batches
    PriorJudge(IndexJudge(), batch_size=2).evaluate(priors, on_progress=seen.append)

    phases = [p["phase"] for p in seen]
    assert phases == ["start", "judging", "judging", "judging"]
    assert all(p["batches_total"] == 3 and p["candidates_total"] == 5 for p in seen)
    # candidates_done advances as whole batches complete (0 before each judging call)
    assert [p["candidates_done"] for p in seen] == [0, 0, 2, 4]
    assert [p["batches_done"] for p in seen] == [0, 0, 1, 2]


def test_maps_indices_back_to_real_ids_per_batch():
    # 3 priors, batch_size 2: batch1 = [x,y] (n=1,2), batch2 = [z] (n=1)
    priors = [_prior("x"), _prior("y"), _prior("z")]
    result = PriorJudge(IndexJudge("reject"), batch_size=2).evaluate(priors)
    assert set(result) == {"x", "y", "z"}


def test_unknown_verdict_defaults_to_borderline():
    resp = json.dumps([{"n": 1, "verdict": "huh", "reason": "x"}])
    result = PriorJudge(StaticJudge(resp)).evaluate([_prior("a")])
    assert result["a"][0] is TriageVerdict.BORDERLINE


def test_out_of_range_or_bogus_index_is_skipped_not_crashed():
    # The judge hallucinates an index that doesn't exist — must be ignored.
    resp = json.dumps([{"n": 99, "verdict": "approve", "reason": "x"}])
    result = PriorJudge(StaticJudge(resp)).evaluate([_prior("a")])
    assert result == {}


def test_handles_markdown_fenced_json():
    resp = "```json\n" + json.dumps([{"n": 1, "verdict": "reject", "reason": "vague"}]) + "\n```"
    result = PriorJudge(StaticJudge(resp)).evaluate([_prior("a")])
    assert result["a"][0] is TriageVerdict.REJECT


def test_malformed_json_raises():
    with pytest.raises(TriageError):
        PriorJudge(StaticJudge("not json")).evaluate([_prior("a")])
