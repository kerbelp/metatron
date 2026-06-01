"""Tests for recording per-ingest run telemetry (for the one-time cost card)."""

from datetime import datetime, timezone

import pytest

from metatron.models import IngestRun
from metatron.storage.sqlite import SQLiteIngestRunStore


@pytest.fixture
def runs() -> SQLiteIngestRunStore:
    s = SQLiteIngestRunStore(":memory:")
    yield s
    s.close()


def _run(repo, model, day=1, **kw) -> IngestRun:
    return IngestRun(
        repo=repo,
        model=model,
        files_parsed=kw.get("files_parsed", 10),
        commits_read=kw.get("commits_read", 50),
        scopes=kw.get("scopes", 5),
        priors_created=kw.get("priors_created", 20),
        input_tokens=kw.get("input_tokens", 1000),
        output_tokens=kw.get("output_tokens", 500),
        timestamp=datetime(2024, 1, day, tzinfo=timezone.utc),
    )


def test_record_and_list_for_repo_round_trips(runs):
    run = _run("r1", "claude-opus-4-8")
    runs.record(run)
    assert runs.list_for_repo("r1") == [run]


def test_list_filters_by_repo_newest_first(runs):
    runs.record(_run("r1", "opus", day=1))
    runs.record(_run("r1", "sonnet", day=3))
    runs.record(_run("r2", "opus", day=2))

    result = runs.list_for_repo("r1")
    assert [r.model for r in result] == ["sonnet", "opus"]  # newest first


def test_list_all_when_repo_none(runs):
    runs.record(_run("r1", "opus"))
    runs.record(_run("r2", "sonnet"))
    assert len(runs.list_for_repo(None)) == 2
