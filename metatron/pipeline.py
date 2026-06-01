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
from pathlib import Path

from pydantic import BaseModel

from metatron.extraction.extractor import PriorExtractor
from metatron.extraction.provider import LLMProvider
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
    priors_created = 0
    for scope_signals in signals.scopes:
        for prior in extractor.extract(scope_signals):
            store.add(prior)
            priors_created += 1

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
