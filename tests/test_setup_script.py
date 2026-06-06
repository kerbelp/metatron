"""Tests for metatron_setup.sh — additive, idempotent onboarding of a target repo."""

import json
import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "metatron_setup.sh"


def run_setup(target: Path, env: dict | None = None):
    # Set a deterministic repo id so tests don't depend on git remotes / uv.
    full_env = {**os.environ, "METATRON_REPO": "github.com/test/repo"}
    if env:
        full_env.update(env)
    result = subprocess.run(
        ["bash", str(SCRIPT), str(target)],
        capture_output=True,
        text=True,
        env=full_env,
    )
    assert result.returncode == 0, result.stderr
    return result


def _mcp(target: Path) -> dict:
    return json.loads((target / ".mcp.json").read_text())


def _settings(target: Path) -> dict:
    return json.loads((target / ".claude" / "settings.json").read_text())


def _userprompt_hook_commands(settings: dict) -> list[str]:
    return _hook_commands(settings, "UserPromptSubmit")


def _hook_commands(settings: dict, event: str) -> list[str]:
    cmds = []
    for entry in settings.get("hooks", {}).get(event, []):
        for h in entry.get("hooks", []):
            cmds.append(h.get("command", ""))
    return cmds


def test_fresh_repo_gets_claude_md_block_and_hook(tmp_path):
    run_setup(tmp_path)

    claude_md = (tmp_path / "CLAUDE.md").read_text()
    assert "METATRON:START" in claude_md
    assert "get_decisions_for_context" in claude_md

    assert (tmp_path / ".claude" / "metatron_reminder.txt").exists()
    cmds = _userprompt_hook_commands(_settings(tmp_path))
    assert any("metatron_reminder" in c for c in cmds)


def test_reminder_text_guides_feedback(tmp_path):
    run_setup(tmp_path)
    reminder = (tmp_path / ".claude" / "metatron_reminder.txt").read_text()
    assert "submit_feedback" in reminder


def test_claude_md_block_guides_feedback(tmp_path):
    run_setup(tmp_path)
    assert "submit_feedback" in (tmp_path / "CLAUDE.md").read_text()


def test_reminder_is_refreshed_on_rerun_so_guidance_propagates(tmp_path):
    # The reminder is the channel the hook injects every turn; re-running must
    # converge it to the current managed text (how already-onboarded repos pick
    # up new guidance like feedback).
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "metatron_reminder.txt").write_text("stale old reminder\n")
    run_setup(tmp_path)
    reminder = (tmp_path / ".claude" / "metatron_reminder.txt").read_text()
    assert "stale old reminder" not in reminder
    assert "submit_feedback" in reminder


def test_installs_stop_hook_for_feedback_reminder(tmp_path):
    run_setup(tmp_path)

    assert (tmp_path / ".claude" / "metatron_feedback_reminder.py").exists()
    stop_cmds = _hook_commands(_settings(tmp_path), "Stop")
    assert any("metatron_feedback_reminder" in c for c in stop_cmds)


def test_stop_hook_is_idempotent_and_preserves_existing(tmp_path):
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    (claude_dir / "settings.json").write_text(
        json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo bye"}]}]}})
    )
    run_setup(tmp_path)
    run_setup(tmp_path)  # twice: must not duplicate

    stop_cmds = _hook_commands(_settings(tmp_path), "Stop")
    assert "echo bye" in stop_cmds  # existing Stop hook kept
    assert sum("metatron_feedback_reminder" in c for c in stop_cmds) == 1


def test_existing_claude_md_is_preserved(tmp_path):
    (tmp_path / "CLAUDE.md").write_text("# My project rules\n\nKeep this line.\n")
    run_setup(tmp_path)

    text = (tmp_path / "CLAUDE.md").read_text()
    assert "Keep this line." in text  # not deleted
    assert "METATRON:START" in text  # block appended


def test_existing_settings_json_is_merged_not_clobbered(tmp_path):
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    (claude_dir / "settings.json").write_text(
        json.dumps(
            {
                "permissions": {"allow": ["Bash(ls:*)"]},
                "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": []}]},
            }
        )
    )
    run_setup(tmp_path)

    settings = _settings(tmp_path)
    assert settings["permissions"]["allow"] == ["Bash(ls:*)"]  # preserved
    assert "PreToolUse" in settings["hooks"]  # preserved
    assert any("metatron_reminder" in c for c in _userprompt_hook_commands(settings))


def test_running_twice_is_idempotent(tmp_path):
    run_setup(tmp_path)
    run_setup(tmp_path)

    claude_md = (tmp_path / "CLAUDE.md").read_text()
    assert claude_md.count("METATRON:START") == 1

    cmds = _userprompt_hook_commands(_settings(tmp_path))
    assert sum("metatron_reminder" in c for c in cmds) == 1


def test_creates_mcp_json_with_metatron_server(tmp_path):
    run_setup(tmp_path)
    server = _mcp(tmp_path)["mcpServers"]["metatron"]
    assert "serve" in server["args"]
    assert "github.com/test/repo" in server["args"]
    if server["command"] == "metatron":
        assert "run" not in server["args"]
    else:
        assert server["command"] == "uv"
        assert "METATRON_DB" in server["env"]


def test_preserves_existing_mcp_servers(tmp_path):
    (tmp_path / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"other": {"command": "x"}}})
    )
    run_setup(tmp_path)
    servers = _mcp(tmp_path)["mcpServers"]
    assert servers["other"]["command"] == "x"  # preserved
    assert "metatron" in servers  # added


def test_does_not_overwrite_existing_metatron_server(tmp_path):
    (tmp_path / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"metatron": {"command": "SENTINEL"}}})
    )
    run_setup(tmp_path)
    assert _mcp(tmp_path)["mcpServers"]["metatron"]["command"] == "SENTINEL"


def test_stray_copy_without_source_fails_clearly(tmp_path):
    # A loose copy of just the script (no Metatron source next to it) must fail
    # with a helpful message, not a cryptic `cp` error.
    stray_dir = tmp_path / "stray"
    stray_dir.mkdir()
    stray_script = stray_dir / "metatron_setup.sh"
    stray_script.write_text(SCRIPT.read_text())
    target = tmp_path / "repo"
    target.mkdir()

    env = {k: v for k, v in os.environ.items() if k != "METATRON_HOME"}
    env["METATRON_REPO"] = "github.com/test/repo"
    result = subprocess.run(
        ["bash", str(stray_script), str(target)],
        capture_output=True, text=True, env=env,
    )
    assert result.returncode != 0
    assert "METATRON_HOME" in result.stderr
    assert not (target / ".claude" / "metatron_feedback_reminder.py").exists()


def test_metatron_home_override_runs_from_anywhere(tmp_path):
    # With METATRON_HOME pointing at the real checkout, a copy run from elsewhere
    # works and installs the feedback hook from that source.
    stray_dir = tmp_path / "stray"
    stray_dir.mkdir()
    stray_script = stray_dir / "metatron_setup.sh"
    stray_script.write_text(SCRIPT.read_text())
    target = tmp_path / "repo"
    target.mkdir()

    run_setup(target, env={"METATRON_HOME": str(SCRIPT.parent)})  # uses canonical source
    # re-run via the stray copy with the override to exercise the copy path
    result = subprocess.run(
        ["bash", str(stray_script), str(target)],
        capture_output=True, text=True,
        env={**os.environ, "METATRON_REPO": "github.com/test/repo",
             "METATRON_HOME": str(SCRIPT.parent)},
    )
    assert result.returncode == 0, result.stderr
    assert (target / ".claude" / "metatron_feedback_reminder.py").exists()


def test_preserves_an_existing_userprompt_hook(tmp_path):
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    (claude_dir / "settings.json").write_text(
        json.dumps(
            {"hooks": {"UserPromptSubmit": [{"hooks": [{"type": "command", "command": "echo hi"}]}]}}
        )
    )
    run_setup(tmp_path)

    cmds = _userprompt_hook_commands(_settings(tmp_path))
    assert "echo hi" in cmds  # existing hook kept
    assert any("metatron_reminder" in c for c in cmds)  # ours added
