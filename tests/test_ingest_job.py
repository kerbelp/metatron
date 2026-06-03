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


def _feedback_candidate(store, pattern):
    return store.add(Prior(repo="github.com/acme/app", pattern=pattern, scope="app",
                           rationale="r", origin=Origin.AGENT_FEEDBACK))


def test_approve_recommended_can_scope_to_one_origin():
    from metatron.webui.api import approve_recommended

    store = SQLitePriorStore(":memory:")
    ingest_pick = _candidate(store, "ingest approve")           # BOOTSTRAP
    fb_pick = _feedback_candidate(store, "feedback approve")     # AGENT_FEEDBACK
    for p in (ingest_pick, fb_pick):
        store.set_triage(p.id, TriageVerdict.APPROVE, "good")

    res = approve_recommended(store, repo="github.com/acme/app", origin="agent_feedback")

    assert res == {"ok": True, "approved": 1}
    assert store.get(fb_pick.id).status is Status.CANONICAL
    assert store.get(ingest_pick.id).status is Status.CANDIDATE  # other origin untouched


def test_triage_job_valuate_then_approve_scoped_to_feedback():
    store = SQLitePriorStore(":memory:")
    fb_good = _feedback_candidate(store, "feedback approve")
    fb_bad = _feedback_candidate(store, "feedback reject")
    ingest_good = _candidate(store, "ingest approve")  # different origin, must be ignored
    verdicts = {
        "feedback approve": TriageVerdict.APPROVE,
        "feedback reject": TriageVerdict.REJECT,
        "ingest approve": TriageVerdict.APPROVE,
    }

    job = TriageJob(store, provider_factory=FakeProvider,
                    judge_factory=lambda p: FakeJudge(verdicts))
    assert job.start("github.com/acme/app", origin="agent_feedback",
                     approve_after=True)["ok"] is True
    s = _wait(job, state="done")

    # only the two feedback candidates were judged; only the approved one promoted
    assert s["total"] == 2 and s["approved"] == 1
    assert store.get(fb_good.id).status is Status.CANONICAL
    assert store.get(fb_bad.id).status is Status.CANDIDATE
    # the ingest candidate was outside scope: never judged, never promoted
    assert store.get(ingest_good.id).triage is TriageVerdict.NONE
    assert store.get(ingest_good.id).status is Status.CANDIDATE


def test_triage_job_approve_after_with_nothing_new_still_approves_prior_winners():
    store = SQLitePriorStore(":memory:")
    already = _feedback_candidate(store, "already judged")
    store.set_triage(already.id, TriageVerdict.APPROVE, "good")  # judged in a prior run

    job = TriageJob(store, provider_factory=FakeProvider,
                    judge_factory=lambda p: FakeJudge({}))
    res = job.start("github.com/acme/app", origin="agent_feedback", approve_after=True)

    assert res["ok"] is True and res["total"] == 0 and res["approved"] == 1
    assert job.status()["state"] == "done"
    assert store.get(already.id).status is Status.CANONICAL


# ---- FeedbackLoopJob ----------------------------------------------------------

from metatron.events import Event, EventKind  # noqa: E402
from metatron.storage.sqlite import SQLiteEventStore  # noqa: E402
from metatron.webui.jobs import FeedbackLoopJob  # noqa: E402


class _LoopRefiner:
    """Turns each gap into one candidate whose pattern echoes the gap text."""

    def __init__(self) -> None:
        self.provider = FakeProvider()

    def refine(self, gap, scope_hint="", task=""):
        return [Prior(repo="placeholder", pattern=f"refined:{gap}", scope=scope_hint or "app",
                      rationale="r", origin=Origin.AGENT_FEEDBACK)]


def test_feedback_loop_refines_then_valuates_then_approves():
    store = SQLitePriorStore(":memory:")
    events = SQLiteEventStore(":memory:")
    events.record(Event(repo="github.com/acme/app", kind=EventKind.FEEDBACK,
                        missing="approve me", area="src/a"))
    events.record(Event(repo="github.com/acme/app", kind=EventKind.FEEDBACK,
                        missing="reject me", area="src/b"))
    # the judge approves the first refined prior, rejects the second
    verdicts = {"refined:approve me": TriageVerdict.APPROVE,
                "refined:reject me": TriageVerdict.REJECT}

    job = FeedbackLoopJob(
        store, events,
        refiner_factory=_LoopRefiner,
        judge_provider_factory=FakeProvider,
        judge_factory=lambda p: FakeJudge(verdicts),
    )
    assert job.start("github.com/acme/app")["ok"] is True
    s = _wait(job, state="done")

    # both gaps refined into candidates; one promoted, one left as a rejected candidate
    assert s["refined"] == 2 and s["valuate_total"] == 2 and s["approved"] == 1
    by_pattern = {p.pattern: p for p in store.list(repo="github.com/acme/app")}
    assert by_pattern["refined:approve me"].status is Status.CANONICAL
    assert by_pattern["refined:reject me"].status is Status.CANDIDATE
    # the feedback events are now handled (idempotent re-runs)
    assert events.unhandled_feedback(repo="github.com/acme/app") == []


def test_feedback_loop_without_provider_is_rejected():
    job = FeedbackLoopJob(SQLitePriorStore(":memory:"), SQLiteEventStore(":memory:"),
                          refiner_factory=None, judge_provider_factory=None)
    res = job.start("github.com/acme/app")
    assert res["ok"] is False and "provider" in res["error"].lower()


def test_feedback_loop_without_event_store_is_rejected():
    job = FeedbackLoopJob(SQLitePriorStore(":memory:"), None,
                          refiner_factory=_LoopRefiner, judge_provider_factory=FakeProvider)
    res = job.start("github.com/acme/app")
    assert res["ok"] is False and "event store" in res["error"].lower()
