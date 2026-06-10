"""Tests for metatron-sync.sh — teammate DB sync through a shared git repo.

The script is exercised end-to-end against a local bare repo standing in for the
shared remote, with shim `metatron` and `launchctl` executables on PATH (the real
CLI and launchd are out of scope here; the shims record how they were called).
"""

import os
import stat
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "metatron-sync.sh"

METATRON_SHIM = """#!/usr/bin/env bash
set -eu
cmd="${1:-}"; shift || true
case "$cmd" in
  export)
    out=""
    while [ $# -gt 0 ]; do
      case "$1" in --out) out="$2"; shift 2 ;; *) shift ;; esac
    done
    printf 'snapshot-%s' "${EXPORT_CONTENT:-default}" > "$out"
    ;;
  import)
    printf 'import %s\\n' "$1" >> "$IMPORT_LOG"
    case "$1" in
      *"${FAIL_IMPORT_FOR:-//never//}"*) echo "boom" >&2; exit 1 ;;
    esac
    ;;
  *) echo "unexpected metatron call: $cmd" >&2; exit 9 ;;
esac
"""

LAUNCHCTL_SHIM = """#!/usr/bin/env bash
printf 'launchctl %s\\n' "$*" >> "$LAUNCHCTL_LOG"
"""


@pytest.fixture
def env(tmp_path):
    """A sandbox: bare 'shared' remote, shims on PATH, redirected sync home/plist dir."""
    bins = tmp_path / "bin"
    bins.mkdir()
    for name, body in (("metatron", METATRON_SHIM), ("launchctl", LAUNCHCTL_SHIM)):
        p = bins / name
        p.write_text(body)
        p.chmod(p.stat().st_mode | stat.S_IEXEC)

    remote = tmp_path / "shared.git"
    subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)

    e = {
        **os.environ,
        "PATH": f"{bins}:{os.environ['PATH']}",
        "METATRON_SYNC_HOME": str(tmp_path / "synchome"),
        "METATRON_SYNC_PLIST_DIR": str(tmp_path / "plists"),
        "IMPORT_LOG": str(tmp_path / "imports.log"),
        "LAUNCHCTL_LOG": str(tmp_path / "launchctl.log"),
        "EXPORT_CONTENT": "v1",
    }
    e.pop("FAIL_IMPORT_FOR", None)
    return {"env": e, "tmp": tmp_path, "remote": remote}


def sync(env, *args, expect=0, extra=None):
    e = dict(env["env"])
    if extra:
        e.update(extra)
    r = subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True, env=e)
    assert r.returncode == expect, f"rc={r.returncode}\nstdout:{r.stdout}\nstderr:{r.stderr}"
    return r


def remote_files(env):
    """File list at the tip of the shared remote ('' when it has no commits)."""
    r = subprocess.run(
        ["git", "-C", str(env["remote"]), "ls-tree", "-r", "--name-only", "HEAD"],
        capture_output=True, text=True,
    )
    return r.stdout.split() if r.returncode == 0 else []


def remote_commits(env):
    r = subprocess.run(
        ["git", "-C", str(env["remote"]), "rev-list", "--count", "HEAD"],
        capture_output=True, text=True,
    )
    return int(r.stdout.strip()) if r.returncode == 0 else 0


def seed_teammate_drop(env, name, content=b"teammate"):
    """Commit drops/<name>.db to the shared remote, as another machine would."""
    work = env["tmp"] / f"seed-{name}"
    subprocess.run(["git", "clone", "-q", str(env["remote"]), str(work)], check=True)
    (work / "drops").mkdir(exist_ok=True)
    (work / "drops" / f"{name}.db").write_bytes(content)
    subprocess.run(["git", "-C", str(work), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(work), "-c", "user.name=seed", "-c", "user.email=s@x",
         "commit", "-q", "-m", f"seed {name}"], check=True)
    subprocess.run(["git", "-C", str(work), "push", "-q", "-u", "origin", "HEAD"], check=True)


def test_script_parses():
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True)


def test_install_clones_schedules_and_pushes_first_drop(env):
    me = subprocess.run(["whoami"], capture_output=True, text=True).stdout.strip()
    r = sync(env, "install", str(env["remote"]))

    home = Path(env["env"]["METATRON_SYNC_HOME"])
    assert (home / "repo" / ".git").is_dir()
    minute = int((home / "minute").read_text().strip())
    assert 0 <= minute <= 59

    plist = Path(env["env"]["METATRON_SYNC_PLIST_DIR"]) / "com.metatron.sync.plist"
    text = plist.read_text()
    assert f"<integer>{minute}</integer>" in text
    assert str(SCRIPT.resolve()) in text
    assert "sync.log" in text
    assert "launchctl load" in Path(env["env"]["LAUNCHCTL_LOG"]).read_text()

    # the first sync ran and published this machine's drop
    assert f"drops/{me}.db" in remote_files(env)
    assert "install complete" in r.stdout


def test_reinstall_keeps_the_same_minute_slot(env):
    sync(env, "install", str(env["remote"]))
    home = Path(env["env"]["METATRON_SYNC_HOME"])
    first = (home / "minute").read_text()
    sync(env, "install", str(env["remote"]))
    assert (home / "minute").read_text() == first


def test_unchanged_export_makes_no_new_commit(env):
    sync(env, "install", str(env["remote"]))
    n = remote_commits(env)
    sync(env, "run")  # same EXPORT_CONTENT -> same snapshot hash -> nothing to publish
    assert remote_commits(env) == n
    sync(env, "run", extra={"EXPORT_CONTENT": "v2"})
    assert remote_commits(env) == n + 1


def test_imports_teammate_drops_and_skips_own(env):
    me = subprocess.run(["whoami"], capture_output=True, text=True).stdout.strip()
    seed_teammate_drop(env, "alice")
    seed_teammate_drop(env, "bob")
    sync(env, "install", str(env["remote"]))

    imports = Path(env["env"]["IMPORT_LOG"]).read_text()
    assert "alice.db" in imports and "bob.db" in imports
    assert f"{me}.db" not in imports


def test_a_failing_import_does_not_abort_the_run(env):
    seed_teammate_drop(env, "alice")
    seed_teammate_drop(env, "bob")
    sync(env, "install", str(env["remote"]), extra={"FAIL_IMPORT_FOR": "//never//"})

    r = sync(env, "run", expect=1, extra={"FAIL_IMPORT_FOR": "alice"})
    imports = Path(env["env"]["IMPORT_LOG"]).read_text()
    assert "bob.db" in imports.split("alice.db", 1)[1]  # bob still imported after alice failed
    assert "1 error(s)" in r.stdout
    assert "import FAILED" in r.stdout


def test_lock_makes_overlapping_runs_exit_early(env):
    sync(env, "install", str(env["remote"]))
    home = Path(env["env"]["METATRON_SYNC_HOME"])
    (home / "lock").mkdir()
    before = Path(env["env"]["IMPORT_LOG"]).read_text() if Path(env["env"]["IMPORT_LOG"]).exists() else ""
    r = sync(env, "run")  # exits 0 without doing work
    assert "lock" in r.stdout
    after = Path(env["env"]["IMPORT_LOG"]).read_text() if Path(env["env"]["IMPORT_LOG"]).exists() else ""
    assert before == after


def test_pull_picks_up_drops_published_after_install(env):
    sync(env, "install", str(env["remote"]))
    seed_teammate_drop(env, "carol")
    sync(env, "run")
    assert "carol.db" in Path(env["env"]["IMPORT_LOG"]).read_text()


def test_uninstall_unloads_and_removes_the_plist(env):
    sync(env, "install", str(env["remote"]))
    plist = Path(env["env"]["METATRON_SYNC_PLIST_DIR"]) / "com.metatron.sync.plist"
    assert plist.exists()
    sync(env, "uninstall")
    assert not plist.exists()
    assert "launchctl unload" in Path(env["env"]["LAUNCHCTL_LOG"]).read_text()


def test_missing_metatron_fails_with_a_clear_message(env, tmp_path):
    sync(env, "install", str(env["remote"]))
    # Drop the recorded path and strip the shim dir from PATH.
    (Path(env["env"]["METATRON_SYNC_HOME"]) / "env").unlink()
    bare_path = "/usr/bin:/bin"
    r = subprocess.run(
        ["bash", str(SCRIPT), "run"], capture_output=True, text=True,
        env={**env["env"], "PATH": bare_path},
    )
    assert r.returncode != 0
    assert "metatron not found" in r.stderr or "git not found" in r.stderr
