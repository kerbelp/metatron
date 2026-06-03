"""Background ingest for the local UI.

The curation UI is single-user and ingests one repo at a time, so this is a
deliberately small single-job runner: ``start()`` kicks ingest off on a daemon
thread and ``status()`` returns a live snapshot (priors landing, tokens, rising
cost) the page polls. Nothing here curates — ingest only ever produces candidates.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path

from metatron.pipeline import ingest as _real_ingest
from metatron.pricing import estimate_cost


class IngestJob:
    """Runs at most one ingest at a time, tracking live progress.

    ``provider_factory`` lazily builds an LLM provider (so the API key is only
    touched when an ingest actually starts); ``None`` means none is configured.
    ``ingest_fn`` is injectable for tests.
    """

    def __init__(
        self,
        store,
        provider_factory: Callable[[], object] | None = None,
        run_store=None,
        ingest_fn: Callable = _real_ingest,
    ) -> None:
        self._store = store
        self._provider_factory = provider_factory
        self._run_store = run_store
        self._ingest_fn = ingest_fn
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._status: dict = {"state": "idle"}

    def status(self) -> dict:
        with self._lock:
            return dict(self._status)

    def start(self, repo_path: str | None, repo: str | None = None) -> dict:
        with self._lock:
            if self._status.get("state") == "running":
                return {"ok": False, "error": "An ingest is already running."}
            if self._provider_factory is None:
                return {
                    "ok": False,
                    "error": "Ingest needs an LLM provider. Set ANTHROPIC_API_KEY "
                             "and restart `metatron ui`.",
                }
            if not repo_path or not Path(repo_path).expanduser().is_dir():
                return {"ok": False, "error": f"Not a directory: {repo_path!r}"}
            path = str(Path(repo_path).expanduser())
            self._status = {
                "state": "running", "phase": "starting", "path": path, "repo": repo,
                "files_parsed": 0, "commits_read": 0, "scopes_total": 0, "scopes_done": 0,
                "priors_created": 0, "input_tokens": 0, "output_tokens": 0,
                "est_cost": None, "error": None,
            }
            self._thread = threading.Thread(
                target=self._run, args=(path, repo), daemon=True
            )
            self._thread.start()
            return {"ok": True}

    def _run(self, repo_path: str, repo: str | None) -> None:
        try:
            provider = self._provider_factory()
        except Exception as exc:  # provider construction failed (bad key, etc.)
            with self._lock:
                self._status.update(state="error", phase="error", error=str(exc))
            return

        def on_progress(p: dict) -> None:
            with self._lock:
                self._status.update(p)
                self._status["phase"] = "extracting"
                self._record_cost(provider)

        try:
            result = self._ingest_fn(
                repo_path, self._store, provider,
                repo=repo, run_store=self._run_store, on_progress=on_progress,
            )
        except Exception as exc:  # parse/provider/network error — surface it
            with self._lock:
                self._status.update(state="error", phase="error", error=str(exc))
                self._record_cost(provider)
            return

        with self._lock:
            self._status.update(
                state="done", phase="done", repo=result.repo,
                files_parsed=result.files_parsed, commits_read=result.commits_read,
                scopes_total=result.scopes, scopes_done=result.scopes,
                priors_created=result.priors_created,
            )
            self._record_cost(provider)

    def _record_cost(self, provider) -> None:
        it = getattr(provider, "input_tokens", 0)
        ot = getattr(provider, "output_tokens", 0)
        self._status["input_tokens"] = it
        self._status["output_tokens"] = ot
        self._status["est_cost"] = estimate_cost(getattr(provider, "model", ""), it, ot)


def _default_judge_factory(provider):
    from metatron.extraction.triage import PriorJudge

    return PriorJudge(provider)


class TriageJob:
    """Runs the advisory judge over a repo's untriaged candidates in the background.

    Advisory only: it sets each candidate's triage verdict + reason; it never
    changes status. The human still curates (see ``approve_recommended``). Chunked
    so the UI can show progress and rising cost while it runs.
    """

    def __init__(
        self,
        store,
        provider_factory: Callable[[], object] | None = None,
        judge_factory: Callable[[object], object] = _default_judge_factory,
        chunk: int = 15,
    ) -> None:
        self._store = store
        self._provider_factory = provider_factory
        self._judge_factory = judge_factory
        self._chunk = max(1, chunk)
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._status: dict = {"state": "idle"}

    def status(self) -> dict:
        with self._lock:
            return dict(self._status)

    def start(
        self, repo: str | None, *, origin: str | None = None, approve_after: bool = False
    ) -> dict:
        """Value a repo's untriaged candidates, optionally approving the winners.

        ``origin`` scopes the batch to one provenance (e.g. ``agent_feedback`` for the
        Feedback screen). ``approve_after`` promotes the candidates the judge rates
        ``approve`` (within the same scope) to canonical when valuation finishes — the
        one-click "valuate then approve high-quality" action. Still human-triggered, so
        the curation invariant holds.
        """
        from metatron.models import Origin, Status, TriageVerdict

        with self._lock:
            if self._status.get("state") == "running":
                return {"ok": False, "error": "A valuation is already running."}
            if self._provider_factory is None:
                return {
                    "ok": False,
                    "error": "Valuation needs an LLM provider. Set ANTHROPIC_API_KEY "
                             "and restart `metatron ui`.",
                }
            origin_enum = Origin(origin) if origin else None
            candidates = self._store.list(
                repo=repo or None, status=Status.CANDIDATE,
                triage=TriageVerdict.NONE, origin=origin_enum,
            )
            if not candidates:
                # Nothing new to judge — but if asked, still approve anything already
                # rated 'approve' in scope (e.g. a prior valuation left winners).
                approved = 0
                if approve_after:
                    approved = self._approve(repo, origin)
                self._status = {
                    "state": "done", "phase": "done", "repo": repo, "origin": origin,
                    "approve_after": approve_after, "approved": approved,
                    "total": 0, "triaged": 0,
                    "counts": {"approve": 0, "borderline": 0, "reject": 0},
                    "input_tokens": 0, "output_tokens": 0, "est_cost": None, "error": None,
                }
                return {"ok": True, "total": 0, "approved": approved}
            self._status = {
                "state": "running", "phase": "valuating", "repo": repo, "origin": origin,
                "approve_after": approve_after, "approved": 0,
                "total": len(candidates), "triaged": 0,
                "counts": {"approve": 0, "borderline": 0, "reject": 0},
                "input_tokens": 0, "output_tokens": 0, "est_cost": None, "error": None,
            }
            self._thread = threading.Thread(
                target=self._run, args=(candidates, repo, origin, approve_after), daemon=True
            )
            self._thread.start()
            return {"ok": True, "total": len(candidates)}

    def _approve(self, repo: str | None, origin: str | None) -> int:
        from metatron.webui.api import approve_recommended

        return approve_recommended(self._store, repo=repo, origin=origin)["approved"]

    def _run(self, candidates, repo, origin, approve_after) -> None:
        try:
            provider = self._provider_factory()
            judge = self._judge_factory(provider)
        except Exception as exc:
            with self._lock:
                self._status.update(state="error", phase="error", error=str(exc))
            return

        try:
            for i in range(0, len(candidates), self._chunk):
                batch = candidates[i : i + self._chunk]
                results = judge.evaluate(batch)
                for prior_id, (verdict, reason) in results.items():
                    try:
                        self._store.set_triage(prior_id, verdict, reason)
                    except KeyError:
                        continue
                with self._lock:
                    self._status["triaged"] += len(batch)
                    for verdict, _ in results.values():
                        self._status["counts"][verdict.value] += 1
                    self._record_cost(provider)
        except Exception as exc:
            with self._lock:
                self._status.update(state="error", phase="error", error=str(exc))
                self._record_cost(provider)
            return

        approved = self._approve(repo, origin) if approve_after else 0
        with self._lock:
            self._status.update(state="done", phase="done", approved=approved)
            self._record_cost(provider)

    def _record_cost(self, provider) -> None:
        it = getattr(provider, "input_tokens", 0)
        ot = getattr(provider, "output_tokens", 0)
        self._status["input_tokens"] = it
        self._status["output_tokens"] = ot
        self._status["est_cost"] = estimate_cost(getattr(provider, "model", ""), it, ot)
