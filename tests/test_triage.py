"""Tests for the triage judge (advisory scoring of candidate decisions).

Candidates are presented to the judge with a small integer index (``n``) and
mapped back locally — the judge never has to echo a uuid, which it gets wrong.
"""

import json
import re

import pytest

from metatron.extraction.provider import LLMProvider
from metatron.extraction.triage import DecisionJudge, TriageError
from metatron.models import Origin, Decision, TriageVerdict


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


def _decision(pid: str) -> Decision:
    return Decision(id=pid, repo="r", pattern=f"pattern {pid}", scope="app", rationale="why", origin=Origin.BOOTSTRAP)


def test_evaluate_returns_a_verdict_and_reason_per_decision():
    decisions = [_decision("aaaa"), _decision("bbbb")]
    result = DecisionJudge(IndexJudge("approve")).evaluate(decisions)
    assert set(result) == {"aaaa", "bbbb"}
    assert result["aaaa"] == (TriageVerdict.APPROVE, "because")


def test_batches_candidates_to_limit_calls():
    judge = IndexJudge()
    DecisionJudge(judge, batch_size=2).evaluate([_decision(str(i)) for i in range(5)])
    assert judge.calls == 3  # ceil(5/2)


def test_evaluate_reports_progress_per_batch():
    seen: list[dict] = []
    decisions = [_decision(str(i)) for i in range(5)]  # batch_size 2 -> 3 batches
    DecisionJudge(IndexJudge(), batch_size=2).evaluate(decisions, on_progress=seen.append)

    phases = [p["phase"] for p in seen]
    assert phases == ["start", "judging", "judging", "judging"]
    assert all(p["batches_total"] == 3 and p["candidates_total"] == 5 for p in seen)
    # candidates_done advances as whole batches complete (0 before each judging call)
    assert [p["candidates_done"] for p in seen] == [0, 0, 2, 4]
    assert [p["batches_done"] for p in seen] == [0, 0, 1, 2]


def test_maps_indices_back_to_real_ids_per_batch():
    # 3 decisions, batch_size 2: batch1 = [x,y] (n=1,2), batch2 = [z] (n=1)
    decisions = [_decision("x"), _decision("y"), _decision("z")]
    result = DecisionJudge(IndexJudge("reject"), batch_size=2).evaluate(decisions)
    assert set(result) == {"x", "y", "z"}


def test_unknown_verdict_defaults_to_borderline():
    resp = json.dumps([{"n": 1, "verdict": "huh", "reason": "x"}])
    result = DecisionJudge(StaticJudge(resp)).evaluate([_decision("a")])
    assert result["a"][0] is TriageVerdict.BORDERLINE


def test_out_of_range_or_bogus_index_is_skipped_not_crashed():
    # The judge hallucinates an index that doesn't exist — must be ignored.
    resp = json.dumps([{"n": 99, "verdict": "approve", "reason": "x"}])
    result = DecisionJudge(StaticJudge(resp)).evaluate([_decision("a")])
    assert result == {}


def test_handles_markdown_fenced_json():
    resp = "```json\n" + json.dumps([{"n": 1, "verdict": "reject", "reason": "vague"}]) + "\n```"
    result = DecisionJudge(StaticJudge(resp)).evaluate([_decision("a")])
    assert result["a"][0] is TriageVerdict.REJECT


def test_malformed_json_raises():
    with pytest.raises(TriageError):
        DecisionJudge(StaticJudge("not json")).evaluate([_decision("a")])
