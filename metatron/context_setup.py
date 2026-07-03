"""Files-first onboarding for a repo (the ``metatron context setup`` command).

Python equivalent of ``metatron_setup_files.sh``, shipped inside the package so an
installed ``metatron`` can onboard a repo without a source checkout. It adds (never
deletes) the artifacts that make a coding agent consult the OKF knowledge base:

1. ``.roo/rules/metatron.md`` — the consult-first rule (managed, refreshed).
2. ``.roo/skills/`` — the OKF authoring/promotion skills (managed copies, from
   the ``metatron/okf_skills`` package data).
3. The knowledge-base scaffold (``candidate/``, ``decisions/``, README) at the
   configured directory — ``context/`` by default, another name via the ``--dir``
   flag, ``METATRON_CONTEXT_DIR``, or ``context_dir`` in ``metatron.toml``.
4. A managed block in ``CLAUDE.md`` between METATRON markers (appended once).

Idempotent: safe to run repeatedly; existing CLAUDE.md content and hand-authored
knowledge-base files are preserved. Monorepos: run once per app dir; workspace-root
artifacts (``.roo/``, root CLAUDE.md) are shared, the knowledge base is per-app.

The METATRON markers are the idempotence key shared with
``metatron_setup_files.sh``: either entry point recognizes (and never duplicates)
a block the other one wrote.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from metatron.config import DEFAULT_CONTEXT_DIR, load_settings

_SKILLS = ("okf-llm-ingest", "okf-promote-candidates")

_RULE_TEXT = """\
# Metatron conventions (files-first)

This repo's coding conventions ("decisions") live as Open Knowledge Format markdown
under `{kb}/`: `{kb}/decisions/` is **canonical**, `{kb}/candidate/` is
**proposed** (unreviewed). In a monorepo each app has its own `{kb}/` — use the
one **nearest** the files you are touching (walk up to the closest `{kb}/`).

- **Consult first.** Before exploring or editing code in an area, read the relevant
  files in the nearest `{kb}/decisions/` and follow them. Say that you did; do
  not rediscover conventions manually until you have.
- **Record gaps as candidates.** Found a durable convention that isn't captured?
  Author it as a new OKF file in the nearest `{kb}/candidate/` (skill:
  `okf-llm-ingest`). Candidates are proposals for human review — never canonical.
- **Never self-promote.** Do not move files into `{kb}/decisions/`. Promotion is
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
`{kb}/` — `{kb}/decisions/` is canonical, `{kb}/candidate/` is proposed
(unreviewed). In a monorepo each app has its own `{kb}/`; use the one **nearest**
the files you are touching.

**Before you Read, Grep, Glob, or Edit code in an area — and before proposing an
implementation — first read the relevant files in the nearest `{kb}/decisions/`
and follow them.** State that you consulted them; do not rediscover conventions
manually until you have.

When you find a durable convention not already captured, **author it as a candidate**:
a new OKF file in the nearest `{kb}/candidate/` (see the `okf-llm-ingest` skill in
`.roo/skills/`). Candidates are uncurated proposals for human review.

**Promotion to canonical is human-gated.** Never move a file into `{kb}/decisions/`
yourself; a human does that via `git mv` reviewed in a pull request (see the
`okf-promote-candidates` skill). Nothing self-promotes.
<!-- METATRON:END -->
"""

_APP_BLOCK = """\
<!-- METATRON:START (managed by metatron context setup — safe to edit inside) -->
## Metatron conventions for this app — consult FIRST

This app's conventions live in `{kb}/` here: `{kb}/decisions/` (canonical),
`{kb}/candidate/` (proposed). Read the relevant `{kb}/decisions/` before
editing this app's code and follow them; record any missing durable convention as a
candidate OKF file in `{kb}/candidate/`. Never self-promote into
`{kb}/decisions/` — promotion is human-gated via `git mv` in a reviewed pull
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
    all apps of a monorepo and live here; the knowledge base lives at the target.
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


def _skill_text(src: Path, kb_name: str) -> str:
    """The packaged skill text, with layout paths rewritten for a custom KB dir.

    The packaged documents describe the default ``context/`` layout; only the
    path references are substituted — command and product names never contain a
    trailing slash, so they are untouched.
    """
    text = src.read_text(encoding="utf-8")
    if kb_name == DEFAULT_CONTEXT_DIR:
        return text
    return (
        text.replace("context/candidate", f"{kb_name}/candidate")
            .replace("context/decisions", f"{kb_name}/decisions")
            .replace("`context/`", f"`{kb_name}/`")
            .replace("<repo>/context/", f"<repo>/{kb_name}/")
    )


def _write_rule(root: Path, kb_name: str, res: SetupResult) -> None:
    rules = root / ".roo" / "rules"
    rules.mkdir(parents=True, exist_ok=True)
    (rules / "metatron.md").write_text(_RULE_TEXT.format(kb=kb_name), encoding="utf-8")
    res.messages.append(f"wrote {rules / 'metatron.md'}")


def _install_skills(root: Path, kb_name: str, res: SetupResult) -> None:
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
        dest.mkdir(parents=True)
        (dest / "SKILL.md").write_text(
            _skill_text(src / "SKILL.md", kb_name), encoding="utf-8")
    res.messages.append(f"installed skills to {dest_root} ({', '.join(_SKILLS)})")


def _scaffold_kb(target: Path, kb_name: str, res: SetupResult) -> None:
    kb = target / kb_name
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


def run_setup(target: Path, dir_name: str | None = None) -> SetupResult:
    """Onboard *target* (a repo or one app of a monorepo) to files-first mode.

    *dir_name* names the knowledge-base directory; when omitted it resolves via
    the ``context_dir`` setting (env/``metatron.toml``), defaulting to ``context``.
    """
    target = target.resolve()
    root = _workspace_root(target)
    kb_name = dir_name or load_settings().context_dir or DEFAULT_CONTEXT_DIR
    res = SetupResult()
    _write_rule(root, kb_name, res)
    _install_skills(root, kb_name, res)
    _scaffold_kb(target, kb_name, res)
    _add_claude_block(root / "CLAUDE.md", _ROOT_BLOCK.format(kb=kb_name), res)
    if target != root:
        _add_claude_block(target / "CLAUDE.md", _APP_BLOCK.format(kb=kb_name), res)
    return res
