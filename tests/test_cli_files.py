"""Tests for the `metatron files` CLI group (lint, index, new, record)."""

import subprocess
import sys
from pathlib import Path


def _run(*args, cwd):
    return subprocess.run(
        [sys.executable, "-m", "metatron.cli", *args],
        cwd=cwd, capture_output=True, text=True)


def _git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


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


def test_files_record_writes_ledger_and_counts(tmp_path):
    repo = tmp_path
    _git("init", cwd=repo)
    _git("config", "user.email", "t@example.com", cwd=repo)
    _git("config", "user.name", "T", cwd=repo)
    d = repo / "metatron" / "decisions"
    d.mkdir(parents=True)
    (d / "token-refresh.md").write_text(
        "---\nid: token-refresh\ntype: decision\nstatus: canonical\ntitle: T\n---\nb\n",
        encoding="utf-8")
    _git("add", "-A", cwd=repo)
    _git("commit", "-m",
         "Use server-side refresh\n\nDecisions-Applied: token-refresh\n", cwd=repo)

    rec = _run("files", "record", "--path", str(d), cwd=repo)
    assert rec.returncode == 0, rec.stdout + rec.stderr

    assert list((d / "log").glob("*.md"))
    assert "references: 1" in (d / "token-refresh.md").read_text()
    assert "token-refresh" in (d / "index.md").read_text()


def test_files_record_quarantines_unknown_id(tmp_path):
    repo = tmp_path
    _git("init", cwd=repo)
    _git("config", "user.email", "t@example.com", cwd=repo)
    _git("config", "user.name", "T", cwd=repo)
    d = repo / "metatron" / "decisions"
    d.mkdir(parents=True)
    (d / "real.md").write_text(
        "---\nid: real\ntype: decision\nstatus: candidate\ntitle: R\n---\nb\n",
        encoding="utf-8")
    _git("add", "-A", cwd=repo)
    _git("commit", "-m", "x\n\nDecisions-Applied: typo-id\n", cwd=repo)

    rec = _run("files", "record", "--path", str(d), cwd=repo)
    assert rec.returncode == 0
    assert "typo-id" in (d / "log" / "unmatched.md").read_text()
    assert "references:" not in (d / "real.md").read_text()
