"""Tests for repo filtering, repo listing, and migration of pre-repo databases."""

import sqlite3

import pytest

from metatron.models import Origin, Prior, Status
from metatron.storage.sqlite import SQLitePriorStore


def _prior(repo, scope="app") -> Prior:
    return Prior(repo=repo, pattern="p", scope=scope, rationale="r", origin=Origin.BOOTSTRAP)


@pytest.fixture
def store() -> SQLitePriorStore:
    s = SQLitePriorStore(":memory:")
    yield s
    s.close()


def test_list_filters_by_repo(store):
    mine = _prior("github.com/me/a")
    theirs = _prior("github.com/them/b")
    store.add(mine)
    store.add(theirs)

    result = store.list(repo="github.com/me/a")
    assert [p.id for p in result] == [mine.id]


def test_count_filters_by_repo(store):
    store.add(_prior("github.com/me/a"))
    store.add(_prior("github.com/me/a"))
    store.add(_prior("github.com/them/b"))
    assert store.count(repo="github.com/me/a") == 2


def test_list_repos_returns_distinct_repos(store):
    store.add(_prior("github.com/me/a"))
    store.add(_prior("github.com/me/a"))
    store.add(_prior("github.com/them/b"))
    assert store.list_repos() == ["github.com/me/a", "github.com/them/b"]


def test_opening_a_pre_repo_database_migrates_and_reads(tmp_path):
    # Simulate a database written before the repo column existed.
    db = str(tmp_path / "legacy.db")
    conn = sqlite3.connect(db)
    conn.execute(
        """CREATE TABLE priors (
            id TEXT PRIMARY KEY, pattern TEXT, scope TEXT, rationale TEXT,
            origin TEXT, confidence TEXT, source_refs TEXT, status TEXT,
            created_at TEXT, updated_at TEXT)"""
    )
    conn.execute(
        "INSERT INTO priors VALUES (?,?,?,?,?,?,?,?,?,?)",
        ("old1", "legacy pattern", "app", "r", "bootstrap", "medium", "[]",
         "candidate", "2024-01-01T00:00:00+00:00", "2024-01-01T00:00:00+00:00"),
    )
    conn.commit()
    conn.close()

    store = SQLitePriorStore(db)  # must migrate without error
    loaded = store.list()

    assert len(loaded) == 1
    assert loaded[0].pattern == "legacy pattern"
    assert loaded[0].repo == ""  # old rows have no repo until backfilled
