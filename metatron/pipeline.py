"""End-to-end ingest: a local git repo -> candidate priors in the store.

Wires the deterministic and LLM halves together:
    tracked files -> parse -> structural facts
    git history   -> commits
    (facts + commits) -> per-scope signals -> LLM extraction -> candidate priors

Dependencies (store, provider) are injected so the pipeline is testable with an
in-memory store and a fake provider, and so the provider/storage stay swappable.
Only git-tracked files are read — untracked scratch files and ignored paths
(``.venv`` etc.) never reach the parser or the model.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel

from metatron.extraction.extractor import PriorExtractor
from metatron.extraction.provider import LLMProvider
from metatron.events import EventKind
from metatron.extraction.signals import collect_signals
from metatron.gitlog.reader import GitLogReader
from metatron.models import IngestRun
from metatron.parsing.base import ParsedFile
from metatron.parsing.registry import get_parser_for_path
from metatron.repo_identity import repo_id
from metatron.storage.base import PriorStore


class IngestResult(BaseModel):
    repo: str
    model: str
    files_parsed: int
    commits_read: int
    scopes: int
    priors_created: int


class RefineResult(BaseModel):
    events_processed: int
    priors_created: int


def refine_feedback(store, event_store, refiner, *, repo=None, limit=None) -> RefineResult:
    """Reshape unhandled feedback gaps into structured candidate priors.

    For each unhandled FEEDBACK event, the ``refiner`` (anything with a
    ``refine(gap, scope_hint, task)`` method) produces structured priors; they are
    stamped with the event's repo and stored as candidates, and the event is marked
    handled (recording the produced candidate ids) so re-runs are idempotent.
    Ratings-only feedback (no gap text) is marked handled without producing priors.
    Human curation still gates everything — nothing here becomes canonical.
    """
    events = event_store.unhandled_feedback(repo=repo)
    if limit is not None:
        events = events[:limit]

    priors_created = 0
    for event in events:
        produced = _refine_one(store, event_store, refiner, event)
        priors_created += len(produced)

    return RefineResult(events_processed=len(events), priors_created=priors_created)


def refine_feedback_event(store, event_store, refiner, event_id: str) -> RefineResult:
    """Refine a single feedback event by id — the manual "Refine" action in the UI.

    Idempotent: an unknown id, a non-feedback event, or an already-handled event is a
    no-op (events_processed=0), so re-clicking can't double-produce candidates.
    """
    event = event_store.get(event_id)
    if event is None or event.kind is not EventKind.FEEDBACK or event.handled:
        return RefineResult(events_processed=0, priors_created=0)
    produced = _refine_one(store, event_store, refiner, event)
    return RefineResult(events_processed=1, priors_created=len(produced))


def _refine_one(store, event_store, refiner, event) -> list[str]:
    """Refine one feedback event into candidates and mark it handled; return their ids."""
    produced: list[str] = []
    if event.missing.strip():
        for prior in refiner.refine(event.missing, event.area, event.task):
            stored = store.add(prior.model_copy(update={"repo": event.repo}))
            produced.append(stored.id)
    event_store.mark_handled(event.id, produced)
    return produced


def ingest(
    repo_path: str | Path,
    store: PriorStore,
    provider: LLMProvider,
    *,
    repo: str | None = None,
    max_commits: int = 500,
    since: str | None = None,
    path_prefix: str | None = None,
    run_store=None,
    on_progress: Callable[[dict], None] | None = None,
) -> IngestResult:
    repo_path = Path(repo_path)
    repo = repo_id(repo_path, override=repo)

    parsed_files = _parse_tracked_files(repo_path, path_prefix)
    paths = [path_prefix] if path_prefix else None
    commits = GitLogReader(repo_path).commits(
        max_commits=max_commits, since=since, paths=paths
    )
    signals = collect_signals(parsed_files, commits)

    model = getattr(provider, "model", "")
    extractor = PriorExtractor(provider, repo, model)
    scopes_total = len(signals.scopes)

    def report(scopes_done: int, priors_created: int) -> None:
        # Per-scope progress so a caller (e.g. the UI) can show priors landing and
        # cost rising live. The provider's token counts are read by the caller.
        if on_progress is not None:
            on_progress({
                "repo": repo,
                "files_parsed": len(parsed_files),
                "commits_read": len(commits),
                "scopes_total": scopes_total,
                "scopes_done": scopes_done,
                "priors_created": priors_created,
            })

    report(0, 0)
    priors_created = 0
    for i, scope_signals in enumerate(signals.scopes, start=1):
        for prior in extractor.extract(scope_signals):
            store.add(prior)
            priors_created += 1
        report(i, priors_created)

    result = IngestResult(
        repo=repo,
        model=model,
        files_parsed=len(parsed_files),
        commits_read=len(commits),
        scopes=len(signals.scopes),
        priors_created=priors_created,
    )
    if run_store is not None:
        run_store.record(
            IngestRun(
                repo=repo,
                model=model,
                files_parsed=result.files_parsed,
                commits_read=result.commits_read,
                scopes=result.scopes,
                priors_created=result.priors_created,
                input_tokens=getattr(provider, "input_tokens", 0),
                output_tokens=getattr(provider, "output_tokens", 0),
            )
        )
    return result


def _parse_tracked_files(
    repo_path: Path, path_prefix: str | None = None
) -> list[ParsedFile]:
    parsed: list[ParsedFile] = []
    for rel in _tracked_files(repo_path, path_prefix):
        parser = get_parser_for_path(rel)
        if parser is None:
            continue
        try:
            source = (repo_path / rel).read_text()
        except (UnicodeDecodeError, OSError):
            continue  # binary or unreadable file — skip
        parsed.append(parser.parse(source, rel))
    return parsed


def _tracked_files(repo_path: Path, path_prefix: str | None = None) -> list[str]:
    args = ["git", "-C", str(repo_path), "ls-files"]
    if path_prefix:
        args.extend(["--", path_prefix])
    result = subprocess.run(args, capture_output=True, text=True, check=True)
    return [line for line in result.stdout.splitlines() if line]
