"""Tests for the `metatron files` CLI group (lint, index, new, record)."""

import subprocess
import sys


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


def test_check_fields_rejects_human_editing_machine_field(tmp_path):
    repo = tmp_path
    _git("init", cwd=repo)
    _git("config", "user.email", "t@example.com", cwd=repo)
    _git("config", "user.name", "T", cwd=repo)
    d = repo / "metatron" / "decisions"
    d.mkdir(parents=True)
    f = d / "d.md"
    f.write_text("---\nid: d\ntype: decision\nstatus: canonical\ntitle: T\n---\nb\n",
                 encoding="utf-8")
    _git("add", "-A", cwd=repo)
    _git("commit", "-m", "add d", cwd=repo)
    base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo,
                          capture_output=True, text=True).stdout.strip()

    # a human hand-edits a machine field
    f.write_text(
        "---\nid: d\ntype: decision\nstatus: canonical\ntitle: T\nreferences: 99\n---\nb\n",
        encoding="utf-8")

    res = _run("files", "check-fields", "--base", base, "--path", str(d),
               "--actor", "human", cwd=repo)
    assert res.returncode != 0
    assert "references" in (res.stdout + res.stderr)


def test_check_fields_with_relative_default_path(tmp_path):
    # Invoked the way CI does: a relative --path inside --repo. A clean tree
    # (no edits) must pass without a path-resolution crash.
    repo = tmp_path
    _git("init", cwd=repo)
    _git("config", "user.email", "t@example.com", cwd=repo)
    _git("config", "user.name", "T", cwd=repo)
    d = repo / "metatron" / "decisions"
    d.mkdir(parents=True)
    (d / "d.md").write_text(
        "---\nid: d\ntype: decision\nstatus: canonical\ntitle: T\n---\nb\n", encoding="utf-8")
    _git("add", "-A", cwd=repo)
    _git("commit", "-m", "add d", cwd=repo)
    base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo,
                          capture_output=True, text=True).stdout.strip()

    res = _run("files", "check-fields", "--base", base,
               "--path", "metatron/decisions", "--repo", ".", cwd=repo)
    assert res.returncode == 0, res.stdout + res.stderr


def test_files_report_renders_digest(tmp_path):
    repo = tmp_path
    _git("init", cwd=repo)
    _git("config", "user.email", "t@example.com", cwd=repo)
    _git("config", "user.name", "T", cwd=repo)
    d = repo / "metatron" / "decisions"
    d.mkdir(parents=True)
    (d / "token-refresh.md").write_text(
        "---\nid: token-refresh\ntype: decision\nstatus: canonical\ntitle: Refresh\n---\nb\n",
        encoding="utf-8")
    _git("add", "-A", cwd=repo)
    _git("commit", "-m", "use it\n\nDecisions-Applied: token-refresh\n", cwd=repo)

    # populate the ledger first
    assert _run("files", "record", "--path", str(d), cwd=repo).returncode == 0

    res = _run("files", "report", "--path", str(d), "--repo", str(repo),
               "--days", "3650", cwd=repo)
    assert res.returncode == 0, res.stdout + res.stderr
    assert "# Decision usage digest" in res.stdout
    assert "token-refresh" in res.stdout
    # the repo's single commit declared the trailer => adoption denominator is 1
    assert "1 of 1 commits (100.0%) consulted a decision." in res.stdout


def test_files_report_writes_out_file(tmp_path):
    repo = tmp_path
    _git("init", cwd=repo)
    _git("config", "user.email", "t@example.com", cwd=repo)
    _git("config", "user.name", "T", cwd=repo)
    d = repo / "metatron" / "decisions"
    d.mkdir(parents=True)
    (d / "a.md").write_text(
        "---\nid: a\ntype: decision\nstatus: candidate\ntitle: A\n---\nb\n", encoding="utf-8")
    _git("add", "-A", cwd=repo)
    _git("commit", "-m", "init", cwd=repo)

    out_file = repo / "digest.md"
    res = _run("files", "report", "--path", str(d), "--repo", str(repo),
               "--out", str(out_file), cwd=repo)
    assert res.returncode == 0
    assert out_file.exists()
    assert "Decision usage digest" in out_file.read_text(encoding="utf-8")
