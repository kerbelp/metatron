#!/usr/bin/env bash
#
# metatron_setup_files.sh — onboard a repo (or one app of a monorepo) to Metatron
# in FILES-FIRST mode: no MCP server, no Claude hooks. The agent reads conventions
# straight from Open Knowledge Format (OKF) markdown under metatron/, and the OKF
# files in git are the source of truth.
#
# Companion to metatron_setup.sh (the MCP version). The differences:
#   - CLAUDE.md gets a "read the metatron/ files first" block (not "query the MCP tool").
#   - A .roo/rules/ rule re-states the directive every turn (Roo loads workspace
#     rules natively) — this replaces the .claude UserPromptSubmit/Stop hooks.
#   - The OKF authoring + promotion skills are copied into .roo/skills/.
#   - The metatron/ knowledge base is scaffolded.
#   - Nothing MCP: no .mcp.json, no .claude/ changes, no feedback script.
#
# Monorepos: run once per app, passing the app dir. Each app keeps its own
# metatron/ co-located with it; the agent consults the metatron/ nearest the code
# it touches. Workspace-root artifacts (.roo/, root CLAUDE.md) are shared and
# refreshed idempotently on every run.
#
# Idempotent: safe to run repeatedly. Existing CLAUDE.md content is preserved; the
# rule and skills are managed copies, refreshed each run.
#
# Usage:  bash metatron_setup_files.sh [target-app-dir]   (defaults to the current dir)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Where the Metatron source lives — defaults to the script's own dir, but can be set
# explicitly so the script works even when run from a copy elsewhere.
METATRON_HOME="${METATRON_HOME:-$SCRIPT_DIR}"

TARGET="${1:-.}"
if [[ ! -d "$TARGET" ]]; then
  echo "error: target directory '$TARGET' does not exist" >&2
  exit 1
fi
TARGET="$(cd "$TARGET" && pwd)"

# The script copies the OKF skills out of the Metatron checkout; a loose copy of just
# this script won't have them — fail early with a clear message.
SKILL_SRC="$METATRON_HOME/.roo/skills"
if [[ ! -f "$SKILL_SRC/okf-llm-ingest/SKILL.md" || ! -f "$SKILL_SRC/okf-promote-candidates/SKILL.md" ]]; then
  echo "error: can't find the OKF skills at '$SKILL_SRC'." >&2
  echo "       Run the script from your Metatron checkout, e.g." >&2
  echo "         bash /path/to/metatron/metatron_setup_files.sh \"$TARGET\"" >&2
  echo "       or set METATRON_HOME=/path/to/metatron and re-run." >&2
  exit 1
fi

# Workspace root = the git toplevel that contains the target (falls back to the
# target itself for a non-git directory). Root-level artifacts (.roo/, the general
# CLAUDE.md block) live here and are shared across all apps in a monorepo; the
# metatron/ knowledge base lives at the target (the app).
WORKSPACE_ROOT="$(git -C "$TARGET" rev-parse --show-toplevel 2>/dev/null || echo "$TARGET")"

echo "Onboarding to Metatron (files-first): $TARGET"
echo "  workspace root: $WORKSPACE_ROOT"

# Appends a managed block between METATRON markers to a CLAUDE.md, once. Existing
# content (and an existing block) is left untouched.
add_claude_block() {
  local md="$1" block="$2"
  if [[ -f "$md" ]] && grep -q "METATRON:START" "$md"; then
    echo "  ${md} already has the Metatron block — left as is"
  else
    printf '\n%s\n' "$block" >> "$md"
    echo "  appended Metatron block to ${md}"
  fi
}

# --- 1. .roo rule (managed, refreshed each run) -----------------------------
ROO_RULES="$WORKSPACE_ROOT/.roo/rules"
mkdir -p "$ROO_RULES"
cat > "$ROO_RULES/metatron.md" <<'EOF'
# Metatron conventions (files-first)

This repo's coding conventions ("decisions") live as Open Knowledge Format markdown
under `metatron/`: `metatron/decisions/` is **canonical**, `metatron/candidate/` is
**proposed** (unreviewed). In a monorepo each app has its own `metatron/` — use the
one **nearest** the files you are touching (walk up to the closest `metatron/`).

- **Consult first.** Before exploring or editing code in an area, read the relevant
  files in the nearest `metatron/decisions/` and follow them. Say that you did; do
  not rediscover conventions manually until you have.
- **Record gaps as candidates.** Found a durable convention that isn't captured?
  Author it as a new OKF file in the nearest `metatron/candidate/` (skill:
  `okf-llm-ingest`). Candidates are proposals for human review — never canonical.
- **Never self-promote.** Do not move files into `metatron/decisions/`. Promotion is
  human-gated: a person `git mv`s the file in a reviewed pull request (skill:
  `okf-promote-candidates`). Nothing self-promotes.
EOF
echo "  wrote $ROO_RULES/metatron.md"

# --- 2. OKF skills (managed copies, refreshed each run) ---------------------
ROO_SKILLS="$WORKSPACE_ROOT/.roo/skills"
if [[ "$SKILL_SRC" -ef "$ROO_SKILLS" ]]; then
  echo "  skills source is the target's own .roo/skills — left as is"
else
  mkdir -p "$ROO_SKILLS"
  for skill in okf-llm-ingest okf-promote-candidates; do
    rm -rf "${ROO_SKILLS:?}/$skill"
    cp -R "$SKILL_SRC/$skill" "$ROO_SKILLS/"
  done
  echo "  copied OKF skills to $ROO_SKILLS (okf-llm-ingest, okf-promote-candidates)"
fi

# --- 3. metatron/ knowledge base (scaffold; never clobbers content) ---------
KB="$TARGET/metatron"
mkdir -p "$KB/candidate" "$KB/decisions"
# .gitkeep so the empty status dirs survive a commit.
[[ -e "$KB/candidate/.gitkeep" ]] || : > "$KB/candidate/.gitkeep"
[[ -e "$KB/decisions/.gitkeep" ]] || : > "$KB/decisions/.gitkeep"
if [[ ! -f "$KB/README.md" ]]; then
  cat > "$KB/README.md" <<'EOF'
# Metatron knowledge base

Open Knowledge Format (OKF) decisions for this app/repo.

- `decisions/` — **canonical** conventions (human-curated). Agents read these first.
- `candidate/` — **proposed** conventions awaiting human review.

Promotion is human-gated: a reviewer `git mv`s a file from `candidate/` to
`decisions/` in a pull request. Rebuild the (optional) serving index with
`metatron mirror import --root .` run from this directory's parent.
EOF
  echo "  scaffolded $KB (candidate/, decisions/, README.md)"
else
  echo "  $KB already scaffolded — left as is"
fi

# --- 4. CLAUDE.md block(s) (append once, between markers) -------------------
# Root block: the general files-first directive + the nearest-wins convention.
ROOT_BLOCK='<!-- METATRON:START (managed by metatron_setup_files.sh — safe to edit inside) -->
## Codebase conventions via Metatron (files) — consult FIRST

This repo'"'"'s conventions ("decisions") live as Open Knowledge Format markdown under
`metatron/` — `metatron/decisions/` is canonical, `metatron/candidate/` is proposed
(unreviewed). In a monorepo each app has its own `metatron/`; use the one **nearest**
the files you are touching.

**Before you Read, Grep, Glob, or Edit code in an area — and before proposing an
implementation — first read the relevant files in the nearest `metatron/decisions/`
and follow them.** State that you consulted them; do not rediscover conventions
manually until you have.

When you find a durable convention not already captured, **author it as a candidate**:
a new OKF file in the nearest `metatron/candidate/` (see the `okf-llm-ingest` skill in
`.roo/skills/`). Candidates are uncurated proposals for human review.

**Promotion to canonical is human-gated.** Never move a file into `metatron/decisions/`
yourself; a human does that via `git mv` reviewed in a pull request (see the
`okf-promote-candidates` skill). Nothing self-promotes.
<!-- METATRON:END -->'
add_claude_block "$WORKSPACE_ROOT/CLAUDE.md" "$ROOT_BLOCK"

# Per-app block: only when the target is a subdirectory (monorepo app). Claude Code
# reads a nested CLAUDE.md when working in that subtree, so the app-specific pointer
# lands right where it is needed.
if [[ "$TARGET" != "$WORKSPACE_ROOT" ]]; then
  APP_BLOCK='<!-- METATRON:START (managed by metatron_setup_files.sh — safe to edit inside) -->
## Metatron conventions for this app — consult FIRST

This app'"'"'s conventions live in `metatron/` here: `metatron/decisions/` (canonical),
`metatron/candidate/` (proposed). Read the relevant `metatron/decisions/` before
editing this app'"'"'s code and follow them; record any missing durable convention as a
candidate OKF file in `metatron/candidate/`. Never self-promote into
`metatron/decisions/` — promotion is human-gated via `git mv` in a reviewed pull
request. See the workspace-root `.roo/skills/` (`okf-llm-ingest`,
`okf-promote-candidates`) for the file format and workflow.
<!-- METATRON:END -->'
  add_claude_block "$TARGET/CLAUDE.md" "$APP_BLOCK"
fi

echo
echo "Done (files-first — no MCP, no hooks). Next steps:"
echo "  - Author candidates into $KB/candidate/ (see .roo/skills/okf-llm-ingest)."
echo "  - Promote reviewed ones with a human-approved 'git mv' to metatron/decisions/."
echo "  - Reconnect Roo / Claude Code so it picks up the new .roo rule and CLAUDE.md."
