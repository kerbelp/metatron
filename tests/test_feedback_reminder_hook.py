"""Tests for metatron_feedback_reminder.py — the Stop hook that nudges feedback.

The hook is invoked by Claude Code with a JSON event on stdin and decides whether to
block the stop (to surface a reminder) by inspecting the session transcript. We drive
it as a subprocess, the way Claude Code does.
"""

import json
import subprocess
import sys
import uuid
from pathlib import Path

HOOK = Path(__file__).parent.parent / "metatron_feedback_reminder.py"


def _transcript(tmp_path: Path, *tool_names: str) -> Path:
    """Write a transcript JSONL where the assistant calls each named tool once."""
    path = tmp_path / "transcript.jsonl"
    lines = []
    for name in tool_names:
        lines.append(json.dumps({
            "type": "assistant",
            "message": {"role": "assistant", "content": [
                {"type": "tool_use", "name": name, "input": {}}
            ]},
        }))
    path.write_text("\n".join(lines) + "\n")
    return path


def _run(event: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(event), capture_output=True, text=True,
    )


def _new_session() -> str:
    return f"sess-{uuid.uuid4()}"  # unique so the per-session marker never collides


def test_blocks_when_queried_but_no_feedback(tmp_path):
    t = _transcript(tmp_path, "mcp__metatron__get_decisions_for_context")
    res = _run({"session_id": _new_session(), "transcript_path": str(t), "stop_hook_active": False})
    out = json.loads(res.stdout)
    assert out["decision"] == "block"
    assert "submit_feedback" in out["reason"]


def test_silent_when_feedback_already_given(tmp_path):
    t = _transcript(tmp_path, "mcp__metatron__get_decisions_for_context",
                    "mcp__metatron__submit_feedback")
    res = _run({"session_id": _new_session(), "transcript_path": str(t), "stop_hook_active": False})
    assert res.stdout.strip() == ""


def test_silent_when_metatron_never_consulted(tmp_path):
    # A turn that never queried Metatron (e.g. answering a question) is not interrupted.
    t = _transcript(tmp_path, "Read", "Bash")
    res = _run({"session_id": _new_session(), "transcript_path": str(t), "stop_hook_active": False})
    assert res.stdout.strip() == ""


def test_silent_when_stop_hook_already_active(tmp_path):
    # We are already continuing because of this hook -> never loop.
    t = _transcript(tmp_path, "mcp__metatron__get_decisions_for_context")
    res = _run({"session_id": _new_session(), "transcript_path": str(t), "stop_hook_active": True})
    assert res.stdout.strip() == ""


def test_reminds_at_most_once_per_session(tmp_path):
    t = _transcript(tmp_path, "mcp__metatron__get_decisions_for_context")
    session = _new_session()
    first = _run({"session_id": session, "transcript_path": str(t), "stop_hook_active": False})
    assert json.loads(first.stdout)["decision"] == "block"
    # Same session, still no feedback — but it already nudged once, so stay quiet.
    second = _run({"session_id": session, "transcript_path": str(t), "stop_hook_active": False})
    assert second.stdout.strip() == ""


def test_malformed_stdin_is_a_silent_noop():
    res = subprocess.run(
        [sys.executable, str(HOOK)], input="not json", capture_output=True, text=True
    )
    assert res.returncode == 0
    assert res.stdout.strip() == ""
