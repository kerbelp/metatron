"""Tests for the background ingest job behind the UI ingest screen."""

import threading
import time

from metatron.pipeline import IngestResult
from metatron.storage.sqlite import SQLitePriorStore
from metatron.webui.jobs import IngestJob


class FakeProvider:
    model = "fake-model"

    def __init__(self) -> None:
        self.input_tokens = 0
        self.output_tokens = 0


def _wait(job, *, state, timeout=2.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        s = job.status()
        if s.get("state") == state:
            return s
        time.sleep(0.01)
    raise AssertionError(f"job never reached {state!r}; last={job.status()}")


def test_start_without_provider_is_rejected(tmp_path):
    job = IngestJob(SQLitePriorStore(":memory:"), provider_factory=None)
    res = job.start(str(tmp_path))
    assert res["ok"] is False and "provider" in res["error"].lower()
    assert job.status()["state"] == "idle"


def test_start_with_bad_path_is_rejected(tmp_path):
    job = IngestJob(SQLitePriorStore(":memory:"), provider_factory=FakeProvider)
    res = job.start(str(tmp_path / "does-not-exist"))
    assert res["ok"] is False
    assert job.status()["state"] == "idle"


def test_ingest_runs_and_reports_progress_and_cost(tmp_path):
    def fake_ingest(repo_path, store, provider, *, repo=None, run_store=None, on_progress=None):
        provider.input_tokens += 100
        provider.output_tokens += 40
        on_progress({"repo": "github.com/acme/app", "scopes_total": 2,
                     "scopes_done": 1, "priors_created": 1})
        provider.input_tokens += 100
        provider.output_tokens += 40
        on_progress({"repo": "github.com/acme/app", "scopes_total": 2,
                     "scopes_done": 2, "priors_created": 2})
        return IngestResult(repo="github.com/acme/app", model="fake-model",
                            files_parsed=3, commits_read=5, scopes=2, priors_created=2)

    job = IngestJob(SQLitePriorStore(":memory:"),
                    provider_factory=FakeProvider, ingest_fn=fake_ingest)
    assert job.start(str(tmp_path))["ok"] is True

    s = _wait(job, state="done")
    assert s["priors_created"] == 2
    assert s["scopes_done"] == s["scopes_total"] == 2
    assert s["repo"] == "github.com/acme/app"
    assert s["input_tokens"] == 200 and s["output_tokens"] == 80
    assert "est_cost" in s  # present (may be None for an unknown model)


def test_double_start_is_rejected_while_running(tmp_path):
    gate = threading.Event()

    def blocking_ingest(repo_path, store, provider, *, repo=None, run_store=None, on_progress=None):
        on_progress({"scopes_total": 1, "scopes_done": 0, "priors_created": 0})
        gate.wait(2.0)
        return IngestResult(repo="r", model="fake-model", files_parsed=0,
                            commits_read=0, scopes=1, priors_created=0)

    job = IngestJob(SQLitePriorStore(":memory:"),
                    provider_factory=FakeProvider, ingest_fn=blocking_ingest)
    assert job.start(str(tmp_path))["ok"] is True
    _wait(job, state="running")

    second = job.start(str(tmp_path))
    assert second["ok"] is False and "running" in second["error"].lower()

    gate.set()
    _wait(job, state="done")


def test_ingest_error_is_captured_not_raised(tmp_path):
    def boom(repo_path, store, provider, *, repo=None, run_store=None, on_progress=None):
        raise RuntimeError("kaboom")

    job = IngestJob(SQLitePriorStore(":memory:"),
                    provider_factory=FakeProvider, ingest_fn=boom)
    assert job.start(str(tmp_path))["ok"] is True
    s = _wait(job, state="error")
    assert "kaboom" in s["error"]


# ---- TriageJob ----------------------------------------------------------------

from metatron.models import Origin, Prior, Status, TriageVerdict  # noqa: E402
from metatron.webui.jobs import TriageJob  # noqa: E402


def _candidate(store, pattern):
    return store.add(Prior(repo="github.com/acme/app", pattern=pattern, scope="app",
                           rationale="r", origin=Origin.BOOTSTRAP))


class FakeJudge:
    def __init__(self, by_pattern):
        self._by_pattern = by_pattern

    def evaluate(self, batch):
        return {
            p.id: (self._by_pattern.get(p.pattern, TriageVerdict.BORDERLINE), "because")
            for p in batch
        }


def test_triage_job_sets_verdicts_and_counts_without_changing_status():
    store = SQLitePriorStore(":memory:")
    a = _candidate(store, "approve me")
    b = _candidate(store, "reject me")
    c = _candidate(store, "meh")
    verdicts = {"approve me": TriageVerdict.APPROVE, "reject me": TriageVerdict.REJECT}

    job = TriageJob(store, provider_factory=FakeProvider,
                    judge_factory=lambda p: FakeJudge(verdicts))
    assert job.start("github.com/acme/app")["ok"] is True
    s = _wait(job, state="done")

    assert s["total"] == 3 and s["triaged"] == 3
    assert s["counts"] == {"approve": 1, "borderline": 1, "reject": 1}
    assert store.get(a.id).triage is TriageVerdict.APPROVE
    assert store.get(b.id).triage is TriageVerdict.REJECT
    # triage never changes status — all still candidates
    for p in (a, b, c):
        assert store.get(p.id).status is Status.CANDIDATE


def test_triage_job_without_provider_is_rejected():
    job = TriageJob(SQLitePriorStore(":memory:"), provider_factory=None)
    res = job.start("github.com/acme/app")
    assert res["ok"] is False and "provider" in res["error"].lower()


def test_triage_job_with_no_candidates_is_done_immediately():
    job = TriageJob(SQLitePriorStore(":memory:"), provider_factory=FakeProvider,
                    judge_factory=lambda p: FakeJudge({}))
    res = job.start("github.com/acme/app")
    assert res["ok"] is True and res["total"] == 0
    assert job.status()["state"] == "done"


def test_approve_recommended_promotes_only_approve_picks():
    from metatron.webui.api import approve_recommended

    store = SQLitePriorStore(":memory:")
    a = _candidate(store, "approve me")
    b = _candidate(store, "reject me")
    c = _candidate(store, "untriaged")
    store.set_triage(a.id, TriageVerdict.APPROVE, "good")
    store.set_triage(b.id, TriageVerdict.REJECT, "bad")
    # c left untriaged

    res = approve_recommended(store, repo="github.com/acme/app")

    assert res == {"ok": True, "approved": 1}
    assert store.get(a.id).status is Status.CANONICAL
    assert store.get(b.id).status is Status.CANDIDATE   # not recommended → untouched
    assert store.get(c.id).status is Status.CANDIDATE
