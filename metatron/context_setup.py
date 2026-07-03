"""Files-first onboarding for a repo (the ``metatron context setup`` command).

Python equivalent of ``metatron_setup_files.sh``, shipped inside the package so an
installed ``metatron`` can onboard a repo without a source checkout. It adds (never
deletes) the artifacts that make a coding agent consult the OKF knowledge base:

1. ``.roo/rules/metatron.md`` — the consult-first rule (managed, refreshed).
2. ``.roo/skills/`` — the OKF authoring/promotion skills (managed copies, from
   the ``metatron/okf_skills`` package data).
3. ``metatron/`` knowledge base scaffold (``candidate/``, ``decisions/``, README).
4. A managed block in ``CLAUDE.md`` between METATRON markers (appended once).

Idempotent: safe to run repeatedly; existing CLAUDE.md content and hand-authored
knowledge-base files are preserved. Monorepos: run once per app dir; workspace-root
artifacts (``.roo/``, root CLAUDE.md) are shared, the ``metatron/`` base is per-app.

The METATRON markers are the idempotence key shared with
``metatron_setup_files.sh``: either entry point recognizes (and never duplicates)
a block the other one wrote.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

_SKILLS = ("okf-llm-ingest", "okf-promote-candidates")

_RULE_TEXT = """\
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
"""

_KB_README = """\
# Metatron knowledge base

Open Knowledge Format (OKF) decisions for this app/repo.

- `decisions/` — **canonical** conventions (human-curated). Agents read these first.
- `candidate/` — **proposed** conventions awaiting human review.

Promotion is human-gated: a reviewer `git mv`s a file from `candidate/` to
`decisions/` in a pull request. Rebuild the (optional) serving index with
`metatron mirror import --root .` run from this directory's parent.
"""

_ROOT_BLOCK = """\
<!-- METATRON:START (managed by metatron context setup — safe to edit inside) -->
## Codebase conventions via Metatron (files) — consult FIRST

This repo's conventions ("decisions") live as Open Knowledge Format markdown under
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
<!-- METATRON:END -->
"""

_APP_BLOCK = """\
<!-- METATRON:START (managed by metatron context setup — safe to edit inside) -->
## Metatron conventions for this app — consult FIRST

This app's conventions live in `metatron/` here: `metatron/decisions/` (canonical),
`metatron/candidate/` (proposed). Read the relevant `metatron/decisions/` before
editing this app's code and follow them; record any missing durable convention as a
candidate OKF file in `metatron/candidate/`. Never self-promote into
`metatron/decisions/` — promotion is human-gated via `git mv` in a reviewed pull
request. See the workspace-root `.roo/skills/` (`okf-llm-ingest`,
`okf-promote-candidates`) for the file format and workflow.
<!-- METATRON:END -->
"""


@dataclass
class SetupResult:
    """What ``run_setup`` did, one human-readable line per artifact."""
    messages: list[str] = field(default_factory=list)


def _workspace_root(target: Path) -> Path:
    """The git toplevel containing *target*, or *target* itself outside git.

    Root-level artifacts (``.roo/``, the general CLAUDE.md block) are shared across
    all apps of a monorepo and live here; the ``metatron/`` base lives at the target.
    """
    try:
        out = subprocess.run(
            ["git", "-C", str(target), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return target
    top = out.stdout.strip()
    return Path(top) if out.returncode == 0 and top else target


def _packaged_skills_dir() -> Path:
    return Path(__file__).resolve().parent / "okf_skills"


def _write_rule(root: Path, res: SetupResult) -> None:
    rules = root / ".roo" / "rules"
    rules.mkdir(parents=True, exist_ok=True)
    (rules / "metatron.md").write_text(_RULE_TEXT, encoding="utf-8")
    res.messages.append(f"wrote {rules / 'metatron.md'}")


def _install_skills(root: Path, res: SetupResult) -> None:
    src_root = _packaged_skills_dir()
    dest_root = root / ".roo" / "skills"
    dest_root.mkdir(parents=True, exist_ok=True)
    for name in _SKILLS:
        src, dest = src_root / name, dest_root / name
        if src.resolve() == dest.resolve():
            res.messages.append(f"{dest} is the packaged source — left as is")
            continue
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(src, dest)
    res.messages.append(f"installed skills to {dest_root} ({', '.join(_SKILLS)})")


def _scaffold_kb(target: Path, res: SetupResult) -> None:
    kb = target / "metatron"
    for status_dir in ("candidate", "decisions"):
        d = kb / status_dir
        d.mkdir(parents=True, exist_ok=True)
        keep = d / ".gitkeep"
        if not keep.exists():
            keep.touch()
    readme = kb / "README.md"
    if readme.exists():
        res.messages.append(f"{kb} already scaffolded — left as is")
    else:
        readme.write_text(_KB_README, encoding="utf-8")
        res.messages.append(f"scaffolded {kb} (candidate/, decisions/, README.md)")


def _add_claude_block(md: Path, block: str, res: SetupResult) -> None:
    if md.exists() and "METATRON:START" in md.read_text(encoding="utf-8"):
        res.messages.append(f"{md} already has the Metatron block — left as is")
        return
    with md.open("a", encoding="utf-8") as f:
        f.write("\n" + block)
    res.messages.append(f"appended Metatron block to {md}")


def run_setup(target: Path) -> SetupResult:
    """Onboard *target* (a repo or one app of a monorepo) to files-first mode."""
    target = target.resolve()
    root = _workspace_root(target)
    res = SetupResult()
    _write_rule(root, res)
    _install_skills(root, res)
    _scaffold_kb(target, res)
    _add_claude_block(root / "CLAUDE.md", _ROOT_BLOCK, res)
    if target != root:
        _add_claude_block(target / "CLAUDE.md", _APP_BLOCK, res)
    return res
