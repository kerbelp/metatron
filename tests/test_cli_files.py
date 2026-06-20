"""Tests for the `metatron files` CLI group (lint, index, new)."""

import subprocess
import sys
from pathlib import Path


def _run(*args, cwd):
    return subprocess.run(
        [sys.executable, "-m", "metatron.cli", *args],
        cwd=cwd, capture_output=True, text=True)


def test_files_new_then_lint_then_index(tmp_path):
    d = tmp_path / "metatron" / "decisions"
    d.mkdir(parents=True)

    new = _run("files", "new", "token-refresh-strategy",
               "--title", "Refresh server-side", "--path", str(d), cwd=tmp_path)
    assert new.returncode == 0
    created = d / "token-refresh-strategy.md"
    assert created.exists()
    assert "status: candidate" in created.read_text()

    lint = _run("files", "lint", "--path", str(d), cwd=tmp_path)
    assert lint.returncode == 0, lint.stdout + lint.stderr

    idx = _run("files", "index", "--path", str(d), cwd=tmp_path)
    assert idx.returncode == 0
    assert (d / "index.md").exists()
    assert "token-refresh-strategy" in (d / "index.md").read_text()


def test_files_lint_fails_on_bad_decision(tmp_path):
    d = tmp_path / "metatron" / "decisions"
    d.mkdir(parents=True)
    (d / "bad.md").write_text(
        "---\nid: bad\ntype: decision\nstatus: nope\ntitle: T\n---\nb\n", encoding="utf-8")
    lint = _run("files", "lint", "--path", str(d), cwd=tmp_path)
    assert lint.returncode != 0
    assert "invalid status" in (lint.stdout + lint.stderr)
