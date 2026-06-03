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
