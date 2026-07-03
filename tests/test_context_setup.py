"""Tests for `metatron context setup` (files-first onboarding)."""

import io
import subprocess
from pathlib import Path

from metatron.cli import main
from metatron.context_setup import _SKILLS, run_setup


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _repo(tmp_path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    return repo


def test_setup_creates_all_artifacts(tmp_path):
    repo = _repo(tmp_path)
    run_setup(repo)
    assert (repo / ".roo" / "rules" / "metatron.md").exists()
    for name in _SKILLS:
        assert (repo / ".roo" / "skills" / name / "SKILL.md").exists()
    assert (repo / "metatron" / "candidate" / ".gitkeep").exists()
    assert (repo / "metatron" / "decisions" / ".gitkeep").exists()
    assert (repo / "metatron" / "README.md").exists()
    claude = (repo / "CLAUDE.md").read_text()
    assert "METATRON:START" in claude and "METATRON:END" in claude


def test_setup_is_idempotent_and_preserves_content(tmp_path):
    repo = _repo(tmp_path)
    (repo / "CLAUDE.md").write_text("# Existing rules\n")
    run_setup(repo)
    (repo / "metatron" / "candidate" / "hand-authored.md").write_text("x")
    first = (repo / "CLAUDE.md").read_text()
    run_setup(repo)
    assert (repo / "CLAUDE.md").read_text() == first          # block appended once
    assert first.startswith("# Existing rules")               # prior content kept
    assert (repo / "metatron" / "candidate" / "hand-authored.md").read_text() == "x"


def test_setup_recognizes_shell_script_marker(tmp_path):
    # A repo onboarded by metatron_setup_files.sh must not get a second block.
    repo = _repo(tmp_path)
    (repo / "CLAUDE.md").write_text(
        "<!-- METATRON:START (managed by metatron_setup_files.sh) -->\nx\n"
        "<!-- METATRON:END -->\n")
    run_setup(repo)
    assert (repo / "CLAUDE.md").read_text().count("METATRON:START") == 1


def test_monorepo_app_gets_own_kb_and_block(tmp_path):
    repo = _repo(tmp_path)
    app = repo / "apps" / "web"
    app.mkdir(parents=True)
    run_setup(app)
    # Shared artifacts at the workspace root; the KB co-located with the app.
    assert (repo / ".roo" / "rules" / "metatron.md").exists()
    assert (app / "metatron" / "candidate").is_dir()
    assert not (repo / "metatron").exists()
    assert "METATRON:START" in (repo / "CLAUDE.md").read_text()
    assert "METATRON:START" in (app / "CLAUDE.md").read_text()


def test_packaged_skills_match_repo_skills():
    # The wheel ships the skills as package data; the copies under .roo/skills
    # are the same documents. They must not drift.
    pkg = Path(__file__).parent.parent / "metatron" / "okf_skills"
    src = Path(__file__).parent.parent / ".roo" / "skills"
    for name in _SKILLS:
        assert (pkg / name / "SKILL.md").read_text() == (src / name / "SKILL.md").read_text()


def test_cli_context_setup_runs_and_reports(tmp_path):
    repo = _repo(tmp_path)
    out = io.StringIO()
    rc = main(["context", "setup", str(repo)], out=out)
    assert rc == 0
    text = out.getvalue()
    assert "Onboarding to Metatron (files-first)" in text
    assert (repo / ".roo" / "rules" / "metatron.md").exists()


def test_cli_context_setup_rejects_missing_dir(tmp_path):
    out = io.StringIO()
    rc = main(["context", "setup", str(tmp_path / "nope")], out=out)
    assert rc == 1
