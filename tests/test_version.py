"""Tests for build/version reporting (the commit served by the UI)."""

import subprocess

from metatron.version import git_revision, version_string


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def test_git_revision_returns_short_hash_for_a_git_repo(tmp_path):
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "t@t.t")
    _git(tmp_path, "config", "user.name", "t")
    _git(tmp_path, "commit", "--allow-empty", "-m", "init")
    expected = subprocess.run(
        ["git", "-C", str(tmp_path), "rev-parse", "--short", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()

    assert git_revision(tmp_path) == expected


def test_git_revision_is_none_outside_a_git_repo(tmp_path):
    assert git_revision(tmp_path) is None


def test_version_string_falls_back_to_unknown(tmp_path):
    assert version_string(tmp_path) == "unknown"
