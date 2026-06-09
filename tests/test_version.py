"""Tests for version reporting + the passive update check (network injected)."""

import subprocess

from metatron import version as V
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


def test_is_newer_compares_dotted_numerics():
    assert V._is_newer("0.10.0", "0.9.0") is True
    assert V._is_newer("0.3.0", "0.2.1") is True
    assert V._is_newer("0.2.1", "0.2.1") is False
    assert V._is_newer("0.2.0", "0.3.0") is False
    assert V._is_newer("garbage", "0.2.1") is False
    assert V._is_newer("0.2.1", "dev") is False


def test_classify_install_path():
    assert V._classify_install_path("/opt/homebrew/Cellar/metatron/0.2.1/lib/...")[1] == "brew upgrade metatron"
    assert V._classify_install_path("/Users/x/.local/pipx/venvs/getmetatron/lib/...")[1] == "pipx upgrade getmetatron"
    assert V._classify_install_path("/Users/x/.local/share/uv/tools/getmetatron/lib/...")[1] == "uv tool upgrade getmetatron"
    assert V._classify_install_path("/usr/lib/python3.12/site-packages/metatron/version.py")[1] == "pip install -U getmetatron"
