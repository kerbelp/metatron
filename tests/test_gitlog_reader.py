"""Tests for reading commit history out of a git repo."""

from metatron.gitlog.reader import Commit, GitLogReader


def test_reads_commits_newest_first(git_repo):
    git_repo.commit("first", {"a.py": "x = 1\n"})
    git_repo.commit("second", {"b.py": "y = 2\n"})

    commits = GitLogReader(git_repo.path).commits()

    assert [c.subject for c in commits] == ["second", "first"]
    assert all(isinstance(c, Commit) for c in commits)


def test_captures_subject_body_author_and_files(git_repo):
    git_repo.commit(
        "fix: handle empty input\n\nThe parser crashed on empty files.",
        {"pkg/parser.py": "def parse(): ...\n", "pkg/util.py": "Z = 0\n"},
    )

    commit = GitLogReader(git_repo.path).commits()[0]

    assert commit.subject == "fix: handle empty input"
    assert "crashed on empty files" in commit.body
    assert commit.author == "Test"
    assert set(commit.files) == {"pkg/parser.py", "pkg/util.py"}
    assert commit.sha


def test_body_is_empty_when_commit_has_no_body(git_repo):
    git_repo.commit("just a subject", {"a.py": "1\n"})
    assert GitLogReader(git_repo.path).commits()[0].body == ""


def test_max_commits_limits_results(git_repo):
    for i in range(5):
        git_repo.commit(f"commit {i}", {"a.py": f"v = {i}\n"})

    commits = GitLogReader(git_repo.path).commits(max_commits=2)
    assert len(commits) == 2
    assert [c.subject for c in commits] == ["commit 4", "commit 3"]


def test_empty_repo_returns_no_commits(git_repo):
    assert GitLogReader(git_repo.path).commits() == []
