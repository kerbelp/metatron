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


def test_upgrade_command_env_override_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("METATRON_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("METATRON_INSTALL_CMD", "my-custom upgrade")
    assert V.upgrade_command() == "my-custom upgrade"


def test_upgrade_command_reads_existing_install_json(monkeypatch, tmp_path):
    monkeypatch.delenv("METATRON_INSTALL_CMD", raising=False)
    monkeypatch.setenv("METATRON_CONFIG_DIR", str(tmp_path))
    (tmp_path / "install.json").write_text('{"upgrade_command": "edited-by-user"}')
    assert V.upgrade_command() == "edited-by-user"


def test_upgrade_command_detects_and_persists_once(monkeypatch, tmp_path):
    monkeypatch.delenv("METATRON_INSTALL_CMD", raising=False)
    monkeypatch.setenv("METATRON_CONFIG_DIR", str(tmp_path))
    calls = {"n": 0}
    def fake_detect():
        calls["n"] += 1
        return ("pip", "pip install -U getmetatron")
    monkeypatch.setattr(V, "detect_install_method", fake_detect)
    assert V.upgrade_command() == "pip install -U getmetatron"
    assert (tmp_path / "install.json").exists()
    assert V.upgrade_command() == "pip install -U getmetatron"
    assert calls["n"] == 1


def _info_env(monkeypatch, tmp_path):
    monkeypatch.setenv("METATRON_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("METATRON_NO_UPDATE_CHECK", raising=False)
    monkeypatch.setenv("METATRON_INSTALL_CMD", "pip install -U getmetatron")
    monkeypatch.setattr(V, "package_version", lambda: "0.2.1")


def test_check_for_update_reports_available(monkeypatch, tmp_path):
    _info_env(monkeypatch, tmp_path)
    info = V.check_for_update(fetch=lambda timeout: {"info": {"version": "0.3.0"}})
    assert info.available is True and info.latest == "0.3.0" and info.current == "0.2.1"
    assert info.command == "pip install -U getmetatron"


def test_check_for_update_not_available_when_current(monkeypatch, tmp_path):
    _info_env(monkeypatch, tmp_path)
    info = V.check_for_update(fetch=lambda timeout: {"info": {"version": "0.2.1"}})
    assert info.available is False


def test_check_for_update_skips_dev_build(monkeypatch, tmp_path):
    _info_env(monkeypatch, tmp_path)
    monkeypatch.setattr(V, "package_version", lambda: "dev")
    assert V.check_for_update(fetch=lambda timeout: {"info": {"version": "9.9.9"}}) is None


def test_check_for_update_disabled_by_env(monkeypatch, tmp_path):
    _info_env(monkeypatch, tmp_path)
    monkeypatch.setenv("METATRON_NO_UPDATE_CHECK", "1")
    assert V.check_for_update(fetch=lambda timeout: {"info": {"version": "9.9.9"}}) is None


def test_check_for_update_throttles(monkeypatch, tmp_path):
    _info_env(monkeypatch, tmp_path)
    calls = {"n": 0}
    def fetch(timeout):
        calls["n"] += 1
        return {"info": {"version": "0.3.0"}}
    V.check_for_update(fetch=fetch)
    V.check_for_update(fetch=fetch)
    assert calls["n"] == 1
    V.check_for_update(fetch=fetch, force=True)
    assert calls["n"] == 2


def test_check_for_update_fail_silent_on_fetch_error(monkeypatch, tmp_path):
    _info_env(monkeypatch, tmp_path)
    def boom(timeout):
        raise OSError("offline")
    info = V.check_for_update(fetch=boom)
    assert info is not None and info.available is False and info.latest is None


def test_format_update_notice():
    assert V.format_update_notice(None) is None
    assert V.format_update_notice(V.UpdateInfo("0.2.1", "0.2.1", False, "x")) is None
    msg = V.format_update_notice(V.UpdateInfo("0.2.1", "0.3.0", True, "brew upgrade metatron"))
    assert "0.3.0" in msg and "brew upgrade metatron" in msg
