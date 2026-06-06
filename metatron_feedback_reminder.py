#!/usr/bin/env python3
"""Metatron Stop hook — nudge the agent to submit_feedback before it finishes.

Installed into a target repo's ``.claude/`` by ``metatron_setup.sh`` and registered
as a ``Stop`` hook. CLAUDE.md guidance alone is unreliable; agents finish a task and
forget to report back. This fires when the agent stops, and *only* if it actually
consulted Metatron this session (called ``get_decisions_for_context``) but never called
``submit_feedback`` — so non-code turns and turns that never touched Metatron are
never interrupted.

It reminds at most once per session and never loops: ``stop_hook_active`` is honoured
(so the agent can always stop after acting), and a per-session marker prevents
re-nagging on later stops. When it does fire it returns ``{"decision": "block"}`` so
the reminder reaches the agent; the agent can submit feedback or, if the task isn't
done, say so and continue.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile

REMINDER = (
    "[Metatron] You consulted Metatron (get_decisions_for_context) this session but "
    "have not called submit_feedback. If the task is complete, call submit_feedback "
    "now: pass the query_id from the decisions output, rate each served decision 1-10 by "
    "its [index] in ratings (10 = exactly right, 1 = misleading) — your ratings tune "
    "which decisions get served first next time — and, most valuable, record any "
    "convention Metatron should have known but didn't in what_was_missing. If the "
    "task is NOT finished yet, say so briefly and continue."
)


def _used_tools(transcript_path: str) -> tuple[bool, bool]:
    """Return (queried, gave_feedback) by scanning the transcript for tool_use blocks.

    Matching real tool_use blocks (not raw text) is deliberate: the injected reminder
    prose mentions both tool names, so a substring search over the transcript would
    always report both as used.
    """
    queried = fed = False
    try:
        with open(transcript_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                content = (event.get("message") or {}).get("content")
                if not isinstance(content, list):
                    continue
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        name = block.get("name", "")
                        if "get_decisions_for_context" in name:
                            queried = True
                        if "submit_feedback" in name:
                            fed = True
    except OSError:
        pass
    return queried, fed


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except (ValueError, OSError):
        return 0

    # Already continuing because of this hook -> let the agent stop.
    if data.get("stop_hook_active"):
        return 0

    session = str(data.get("session_id") or "")
    marker = (
        os.path.join(tempfile.gettempdir(), f"metatron_fb_{session}")
        if session
        else ""
    )
    if marker and os.path.exists(marker):
        return 0  # already reminded once this session

    queried, fed = _used_tools(data.get("transcript_path") or "")
    if queried and not fed:
        if marker:
            try:
                open(marker, "w").close()
            except OSError:
                pass
        print(json.dumps({"decision": "block", "reason": REMINDER}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
