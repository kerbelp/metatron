#!/usr/bin/env bash
# metatron-sync.sh — sync Metatron SQLite databases between teammates via a shared git repo.
#
# Each teammate's machine exports its own database snapshot to drops/<username>.db in a
# shared git repo and imports everyone else's drops. Export is a consistent snapshot
# (sqlite backup + vacuum) — the live DB file is never copied directly. Import dedupes
# by id, so re-importing the same drop is a no-op.
#
# Usage:
#   ./metatron-sync.sh install <git-remote-url>   set up the repo, schedule, and run once
#   ./metatron-sync.sh run                        perform one sync (what the scheduler calls)
#   ./metatron-sync.sh uninstall                  unload and remove the launchd agent
#
# Scheduling uses a launchd user agent, not cron: cron skips runs while the Mac sleeps,
# launchd runs a missed StartCalendarInterval job once the machine wakes. Each machine
# picks a random minute of the hour ONCE and persists it, so a small team spreads its
# pushes across the hour and keeps the same slot across reinstalls.
#
# launchd agents get a minimal PATH, so absolute paths to git and metatron are resolved
# at install time and baked into an env file the run mode sources.

set -euo pipefail

SYNC_HOME="${METATRON_SYNC_HOME:-$HOME/.metatron-sync}"
REPO_DIR="$SYNC_HOME/repo"
ENV_FILE="$SYNC_HOME/env"
MINUTE_FILE="$SYNC_HOME/minute"
LOCK_DIR="$SYNC_HOME/lock"
LOG_FILE="$SYNC_HOME/sync.log"
PLIST_LABEL="com.metatron.sync"
PLIST_DIR="${METATRON_SYNC_PLIST_DIR:-$HOME/Library/LaunchAgents}"
PLIST_PATH="$PLIST_DIR/$PLIST_LABEL.plist"

log() { printf '%s %s\n' "$(date '+%Y-%m-%dT%H:%M:%S')" "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

# Resolve the absolute paths to git/metatron. At install time this records them into
# ENV_FILE; at run time the recorded paths win (launchd PATH is minimal), with a PATH
# lookup as fallback so `run` also works standalone from a normal shell.
resolve_tools() {
    if [ -f "$ENV_FILE" ]; then
        # shellcheck source=/dev/null
        . "$ENV_FILE"
    fi
    GIT_BIN="${GIT_BIN:-$(command -v git || true)}"
    METATRON_BIN="${METATRON_BIN:-$(command -v metatron || true)}"
    [ -n "$GIT_BIN" ] && [ -x "$GIT_BIN" ] || die "git not found on PATH (or recorded path is stale); install git or re-run: $0 install <remote>"
    [ -n "$METATRON_BIN" ] && [ -x "$METATRON_BIN" ] || die "metatron not found on PATH (or recorded path is stale); pip install getmetatron or re-run: $0 install <remote>"
}

repo_git() { "$GIT_BIN" -C "$REPO_DIR" "$@"; }

# --- install -------------------------------------------------------------------------

cmd_install() {
    remote="${1:-}"
    [ -n "$remote" ] || die "usage: $0 install <git-remote-url>"
    resolve_tools
    mkdir -p "$SYNC_HOME" "$PLIST_DIR"

    if [ -d "$REPO_DIR/.git" ]; then
        log "sync repo already cloned at $REPO_DIR — keeping it"
    else
        "$GIT_BIN" clone "$remote" "$REPO_DIR"
    fi
    # Commits need an identity even on machines with no global git config.
    if [ -z "$(repo_git config user.email || true)" ]; then
        repo_git config user.name "$(whoami)"
        repo_git config user.email "$(whoami)@metatron-sync.local"
    fi

    # Pick the hourly slot once; keep it across reinstalls so the team's slots stay
    # spread out instead of being reshuffled on every machine refresh.
    if [ ! -f "$MINUTE_FILE" ]; then
        printf '%s\n' "$((RANDOM % 60))" > "$MINUTE_FILE"
    fi
    minute="$(cat "$MINUTE_FILE")"

    # Record the tool paths for the launchd run (minimal PATH there).
    {
        printf 'GIT_BIN=%q\n' "$GIT_BIN"
        printf 'METATRON_BIN=%q\n' "$METATRON_BIN"
    } > "$ENV_FILE"

    script_path="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
    cat > "$PLIST_PATH" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$PLIST_LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>$script_path</string>
        <string>run</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Minute</key>
        <integer>$minute</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>$LOG_FILE</string>
    <key>StandardErrorPath</key>
    <string>$LOG_FILE</string>
</dict>
</plist>
PLIST

    launchctl unload "$PLIST_PATH" 2>/dev/null || true
    launchctl load "$PLIST_PATH"
    log "scheduled hourly sync at minute $minute (agent: $PLIST_PATH, log: $LOG_FILE)"

    log "running first sync now…"
    if cmd_run; then
        log "install complete — first sync succeeded"
    else
        die "install wrote the schedule, but the first sync FAILED — see messages above"
    fi
}

# --- run -----------------------------------------------------------------------------

# Rebase-pull the shared repo. Only this machine ever writes drops/<me>.db, so a
# conflict there only happens replaying our not-yet-pushed commit; either side is fine
# because a fresh export overwrites the file immediately after. Any other conflict is
# unexpected: abort the rebase (leaving the repo clean) and fail the run.
pull_shared() {
    drop_rel="$1"
    # A just-created shared repo has no commits yet: nothing to pull.
    if ! repo_git ls-remote --exit-code --heads origin >/dev/null 2>&1; then
        log "remote has no branches yet — skipping pull (first sync seeds it)"
        return 0
    fi
    if repo_git pull --rebase --quiet; then
        return 0
    fi
    conflicted="$(repo_git diff --name-only --diff-filter=U)"
    if [ "$conflicted" = "$drop_rel" ]; then
        log "rebase conflict on our own drop file — resolving with the local copy"
        repo_git checkout --theirs -- "$drop_rel"
        repo_git add "$drop_rel"
        GIT_EDITOR=true repo_git rebase --continue
        return 0
    fi
    repo_git rebase --abort || true
    die "pull --rebase hit conflicts outside our own drop file: ${conflicted:-unknown}"
}

file_hash() {
    if [ -f "$1" ]; then shasum -a 256 "$1" | cut -d' ' -f1; else printf 'missing'; fi
}

cmd_run() {
    resolve_tools
    [ -d "$REPO_DIR/.git" ] || die "no sync repo at $REPO_DIR — run: $0 install <remote>"
    mkdir -p "$SYNC_HOME"

    # Exclusive lock: overlapping runs (a slow sync meeting the next hourly tick) exit
    # early instead of racing the repo. mkdir is atomic on local filesystems.
    if ! mkdir "$LOCK_DIR" 2>/dev/null; then
        log "another sync holds the lock at $LOCK_DIR — exiting"
        return 0
    fi
    trap 'rmdir "$LOCK_DIR" 2>/dev/null || true' EXIT

    me="$(whoami)"
    drop_rel="drops/$me.db"
    drop_abs="$REPO_DIR/$drop_rel"

    pull_shared "$drop_rel"
    mkdir -p "$REPO_DIR/drops"

    # Export a consistent snapshot over our drop. NEVER copy the live DB file —
    # `metatron export` uses sqlite's backup API so the artifact is never mid-write.
    before="$(file_hash "$drop_abs")"
    "$METATRON_BIN" export --out "$drop_abs" || die "metatron export failed"
    after="$(file_hash "$drop_abs")"

    # Import every teammate's drop. Idempotent per file (dedupe by id), and one bad
    # file must not abort the rest of the run — log it and keep going.
    imported=0
    errors=0
    for f in "$REPO_DIR"/drops/*.db; do
        [ -e "$f" ] || continue   # unmatched glob
        [ "$f" = "$drop_abs" ] && continue
        if "$METATRON_BIN" import "$f" >/dev/null 2>&1; then
            imported=$((imported + 1))
        else
            errors=$((errors + 1))
            log "import FAILED for $f — continuing"
        fi
    done

    # Publish only when our snapshot actually changed; otherwise every machine would
    # commit an identical drop every hour.
    if [ "$before" != "$after" ]; then
        repo_git add "$drop_rel"
        repo_git commit --quiet -m "sync $me $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
        if ! repo_git push --quiet -u origin HEAD; then
            log "push rejected — pulling and retrying once"
            pull_shared "$drop_rel"
            repo_git push --quiet -u origin HEAD
        fi
    fi

    size="$(wc -c < "$drop_abs" | tr -d ' ')"
    log "sync done: exported ${size}B, imported $imported file(s), $errors error(s)"
    [ "$errors" -eq 0 ]
}

# --- uninstall -----------------------------------------------------------------------

cmd_uninstall() {
    if [ -f "$PLIST_PATH" ]; then
        launchctl unload "$PLIST_PATH" 2>/dev/null || true
        rm -f "$PLIST_PATH"
        log "removed launchd agent $PLIST_PATH (data in $SYNC_HOME kept)"
    else
        log "no agent installed at $PLIST_PATH — nothing to do"
    fi
}

# --- dispatch ------------------------------------------------------------------------

case "${1:-}" in
    install)   shift; cmd_install "$@" ;;
    run)       cmd_run ;;
    uninstall) cmd_uninstall ;;
    *)         die "usage: $0 {install <git-remote-url>|run|uninstall}" ;;
esac
