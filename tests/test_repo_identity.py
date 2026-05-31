"""Tests for deriving a stable repo identity from the git remote."""

import subprocess

import pytest

from metatron.repo_identity import normalize_remote, repo_id


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://github.com/kerbelp/www-ai-collection.git", "github.com/kerbelp/www-ai-collection"),
        ("https://github.com/org/repo", "github.com/org/repo"),
        ("git@github.com:org/repo.git", "github.com/org/repo"),
        ("ssh://git@github.com/org/repo.git", "github.com/org/repo"),
        ("https://github.com/org/repo/", "github.com/org/repo"),
        ("git@gitlab.example.com:team/sub/proj.git", "gitlab.example.com/team/sub/proj"),
    ],
)
def test_normalize_remote(url, expected):
    assert normalize_remote(url) == expected


def test_repo_id_uses_origin_remote(git_repo):
    subprocess.run(
        ["git", "remote", "add", "origin", "git@github.com:org/cool-repo.git"],
        cwd=git_repo.path, check=True,
    )
    assert repo_id(git_repo.path) == "github.com/org/cool-repo"


def test_repo_id_override_wins(git_repo):
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/org/repo.git"],
        cwd=git_repo.path, check=True,
    )
    assert repo_id(git_repo.path, override="custom-name") == "custom-name"


def test_repo_id_falls_back_to_directory_name_without_remote(git_repo):
    # No remote configured -> fall back to the repo directory's name.
    assert repo_id(git_repo.path) == git_repo.path.name
