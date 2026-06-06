#!/usr/bin/env bash
#
# metatron_setup.sh — onboard a repo to Metatron.
#
# Adds (never deletes) two things to the target repo so its coding agent reliably
# consults Metatron:
#   1. A hard-gate block in CLAUDE.md (between METATRON markers).
#   2. A UserPromptSubmit hook in .claude/settings.json that re-injects the
#      directive into context every turn.
#
# Idempotent: safe to run repeatedly. Existing CLAUDE.md content and other
# settings.json keys/hooks are preserved.
#
# Usage:  bash metatron_setup.sh [target-repo-dir]   (defaults to the current dir)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Where the Metatron source lives — defaults to the script's own dir, but can be
# set explicitly so the script works even when run from a copy elsewhere.
METATRON_HOME="${METATRON_HOME:-$SCRIPT_DIR}"

TARGET="${1:-.}"
if [[ ! -d "$TARGET" ]]; then
  echo "error: target directory '$TARGET' does not exist" >&2
  exit 1
fi
TARGET="$(cd "$TARGET" && pwd)"

# The script needs the Metatron source (the feedback-hook file and the package)
# to onboard a repo. A loose copy of just this script won't have them — fail with
# a clear message rather than a cryptic `cp`/import error later.
if [[ ! -f "$METATRON_HOME/metatron_feedback_reminder.py" || ! -f "$METATRON_HOME/metatron/repo_identity.py" ]]; then
  echo "error: can't find the Metatron source at '$METATRON_HOME'." >&2
  echo "       Run the script from your Metatron checkout, e.g." >&2
  echo "         bash /path/to/metatron/metatron_setup.sh \"$TARGET\"" >&2
  echo "       or set METATRON_HOME=/path/to/metatron and re-run." >&2
  exit 1
fi

CLAUDE_MD="$TARGET/CLAUDE.md"
CLAUDE_DIR="$TARGET/.claude"
SETTINGS="$CLAUDE_DIR/settings.json"
REMINDER="$CLAUDE_DIR/metatron_reminder.txt"
HOOK_CMD='cat "${CLAUDE_PROJECT_DIR:-.}/.claude/metatron_reminder.txt"'

echo "Onboarding to Metatron: $TARGET"
mkdir -p "$CLAUDE_DIR"

# --- 1. reminder text (managed by Metatron) --------------------------------
cat > "$REMINDER" <<'EOF'
[Metatron] Before exploring (Read/Grep/Glob) or editing code for this task,
FIRST call the metatron MCP tool `get_decisions_for_context(file_path_or_area,
task_description)` for the area you'll touch, and follow the decisions it returns.
Do not rediscover conventions manually until you've consulted Metatron. If you
learn a durable new convention, record it via `submit_candidate_decision(...)`.
When the task is done, call `submit_feedback(query_id, ratings, what_was_missing)`:
pass the query id from the decisions output, rate each served decision 1-10 by its
[index] in `ratings` (10 = exactly right, 1 = misleading) — ratings tune which
decisions get served first next time — and, most important, report any convention
Metatron should have known but didn't. Gap reports become candidates for human
review; nothing you send is auto-applied to the canonical set.
EOF
echo "  wrote $REMINDER"

# --- 1b. Stop-hook script (managed copy, refreshed each run) ----------------
# Nudges the agent to submit_feedback when it finishes a task where it consulted
# Metatron — CLAUDE.md guidance alone is unreliable.
FEEDBACK_HOOK="$CLAUDE_DIR/metatron_feedback_reminder.py"
cp "$METATRON_HOME/metatron_feedback_reminder.py" "$FEEDBACK_HOOK"
echo "  wrote $FEEDBACK_HOOK"

# --- 2. CLAUDE.md block (append once, between markers) ----------------------
if [[ -f "$CLAUDE_MD" ]] && grep -q "METATRON:START" "$CLAUDE_MD"; then
  echo "  CLAUDE.md already has the Metatron block — left as is"
else
  cat >> "$CLAUDE_MD" <<'EOF'

<!-- METATRON:START (managed by metatron_setup.sh — safe to edit inside) -->
## Codebase conventions via Metatron (MCP) — query FIRST

This repo's conventions ("decisions") are served by the **metatron** MCP server.

**Before you Read, Grep, Glob, or Edit code in any area — and before proposing an
implementation — you MUST first call `get_decisions_for_context(file_path_or_area,
task_description)` for that area and follow what it returns.** Do not explore the
codebase to rediscover conventions until you have consulted Metatron; state that
you did.

When you find a durable convention not already covered, call
`submit_candidate_decision(pattern, scope, rationale, confidence)`. It is stored
as an uncurated candidate for human review and is never treated as canonical
automatically.

**After completing the task, give feedback** via `submit_feedback(query_id,
ratings, what_was_missing, missing_scope)`: reference the `query_id` Metatron
returned with the decisions, **rate each served decision 1-10 by its `[index]`** in
`ratings` (10 = exactly right, 1 = misleading) — your ratings automatically tune
which decisions get served first next time — and, most valuably, record any convention
Metatron should have known but didn't. Ratings reorder what's served; they never
promote, demote, or reject a decision — crossing the canonical set is always a human's
call.
<!-- METATRON:END -->
EOF
  echo "  appended Metatron block to CLAUDE.md"
fi

# --- 3. UserPromptSubmit hook (merge into settings.json, additive) ----------
python3 - "$SETTINGS" "$HOOK_CMD" <<'PYEOF'
import json, os, sys

path, cmd = sys.argv[1], sys.argv[2]
data = {}
if os.path.exists(path):
    with open(path) as f:
        text = f.read().strip()
    data = json.loads(text) if text else {}

hooks = data.setdefault("hooks", {})
ups = hooks.setdefault("UserPromptSubmit", [])

already = any(
    "metatron_reminder" in h.get("command", "")
    for entry in ups
    for h in entry.get("hooks", [])
)
if already:
    print("  settings.json already has the Metatron hook — left as is")
else:
    ups.append({"hooks": [{"type": "command", "command": cmd}]})
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    print(f"  added UserPromptSubmit hook to {path}")
PYEOF

# --- 3b. Stop hook (merge into settings.json, additive) ---------------------
STOP_CMD='python3 "${CLAUDE_PROJECT_DIR:-.}/.claude/metatron_feedback_reminder.py"'
python3 - "$SETTINGS" "$STOP_CMD" <<'PYEOF'
import json, os, sys

path, cmd = sys.argv[1], sys.argv[2]
data = {}
if os.path.exists(path):
    with open(path) as f:
        text = f.read().strip()
    data = json.loads(text) if text else {}

hooks = data.setdefault("hooks", {})
stop = hooks.setdefault("Stop", [])

already = any(
    "metatron_feedback_reminder" in h.get("command", "")
    for entry in stop
    for h in entry.get("hooks", [])
)
if already:
    print("  settings.json already has the Metatron Stop hook — left as is")
else:
    stop.append({"hooks": [{"type": "command", "command": cmd}]})
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    print(f"  added Stop hook to {path}")
PYEOF

# Helper to derive repo ID in pure shell
derive_repo_id() {
  local target_dir="$1"
  local origin_url
  origin_url="$(git -C "$target_dir" remote get-url origin 2>/dev/null || true)"
  if [[ -n "$origin_url" ]]; then
    local host path_part url_clean scp_regex
    scp_regex="^([a-zA-Z0-9._-]+@)?([a-zA-Z0-9._-]+):(.+)$"
    if [[ "$origin_url" =~ $scp_regex ]]; then
      host="${BASH_REMATCH[2]}"
      path_part="${BASH_REMATCH[3]}"
      path_part="${path_part#/}"
      path_part="${path_part%.git}"
      echo "${host}/${path_part}"
    else
      url_clean="${origin_url#*://}"
      url_clean="${url_clean#*@}"
      url_clean="${url_clean%.git}"
      echo "${url_clean%/}"
    fi
  else
    basename "$target_dir"
  fi
}

# --- 4. MCP server config (.mcp.json, additive) ----------------------------
MCP_FILE="$TARGET/.mcp.json"
DB_PATH="${METATRON_DB:-$METATRON_HOME/metatron.db}"
REPO_ID="${METATRON_REPO:-}"
if [[ -z "$REPO_ID" ]]; then
  # Use shell helper so we don't depend on python/uv sync state at this stage.
  REPO_ID="$(derive_repo_id "$TARGET" || true)"
fi
if [[ -z "$REPO_ID" ]]; then
  echo "  warning: could not derive repo id; skipping .mcp.json" >&2
  echo "           (set METATRON_REPO=<id> or add an origin remote, then re-run)" >&2
else
  # If metatron CLI is globally available on PATH, use it directly
  if command -v metatron >/dev/null 2>&1; then
    if [[ -n "${METATRON_DB:-}" ]]; then
      SERVER_JSON="$(python3 -c 'import json,sys; print(json.dumps({"command":"metatron","args":["serve","--repo",sys.argv[1]],"env":{"METATRON_DB":sys.argv[2]}}))' \
        "$REPO_ID" "$METATRON_DB")"
    else
      SERVER_JSON="$(python3 -c 'import json,sys; print(json.dumps({"command":"metatron","args":["serve","--repo",sys.argv[1]]}))' \
        "$REPO_ID")"
    fi
  else
    # Fallback to running local check-out via uv project environment
    SERVER_JSON="$(python3 -c 'import json,sys; print(json.dumps({"command":"uv","args":["run","--project",sys.argv[1],"metatron","serve","--repo",sys.argv[2]],"env":{"METATRON_DB":sys.argv[3]}}))' \
      "$METATRON_HOME" "$REPO_ID" "$DB_PATH")"
  fi
  python3 - "$MCP_FILE" "$SERVER_JSON" <<'PYEOF'
import json, os, sys

path, server_json = sys.argv[1], sys.argv[2]
data = {}
if os.path.exists(path):
    text = open(path).read().strip()
    data = json.loads(text) if text else {}
servers = data.setdefault("mcpServers", {})
if "metatron" in servers:
    print("  .mcp.json already has the metatron server — left as is")
else:
    servers["metatron"] = json.loads(server_json)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    print(f"  added metatron server to {path}")
PYEOF
fi

echo
echo "Done. Next step:"
echo "  - Restart / reconnect Claude Code so it loads the hook and MCP server."
