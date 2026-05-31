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

TARGET="${1:-.}"
if [[ ! -d "$TARGET" ]]; then
  echo "error: target directory '$TARGET' does not exist" >&2
  exit 1
fi
TARGET="$(cd "$TARGET" && pwd)"

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
FIRST call the metatron MCP tool `get_priors_for_context(file_path_or_area,
task_description)` for the area you'll touch, and follow the priors it returns.
Do not rediscover conventions manually until you've consulted Metatron. If you
learn a durable new convention, record it via `submit_candidate_learning(...)`.
EOF
echo "  wrote $REMINDER"

# --- 2. CLAUDE.md block (append once, between markers) ----------------------
if [[ -f "$CLAUDE_MD" ]] && grep -q "METATRON:START" "$CLAUDE_MD"; then
  echo "  CLAUDE.md already has the Metatron block — left as is"
else
  cat >> "$CLAUDE_MD" <<'EOF'

<!-- METATRON:START (managed by metatron_setup.sh — safe to edit inside) -->
## Codebase conventions via Metatron (MCP) — query FIRST

This repo's conventions ("priors") are served by the **metatron** MCP server.

**Before you Read, Grep, Glob, or Edit code in any area — and before proposing an
implementation — you MUST first call `get_priors_for_context(file_path_or_area,
task_description)` for that area and follow what it returns.** Do not explore the
codebase to rediscover conventions until you have consulted Metatron; state that
you did.

When you find a durable convention not already covered, call
`submit_candidate_learning(pattern, scope, rationale, confidence)`. It is stored
as an uncurated candidate for human review and is never treated as canonical
automatically.
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

echo
echo "Done. Next steps:"
echo "  - Ensure .mcp.json points the 'metatron' server at this repo (metatron serve --repo <id>)."
echo "  - Restart / reconnect Claude Code so it loads the hook and MCP server."
