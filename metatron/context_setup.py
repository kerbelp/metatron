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
4. A managed block in ``AGENTS.md`` between METATRON markers — appended to an
   existing file, never overwriting surrounding content; an existing managed
   block is refreshed in place so a re-run (e.g. with a different
   ``--review-gate``) updates the contract.

The generated contract depends on the repo's **review gate** (see
``config.REVIEW_GATES``): with ``pr`` (the default) agents author decisions
directly under ``decisions/`` on a working branch and the pull-request review is
the human curation act; with ``candidates`` they stage proposals under
``candidate/`` and a human promotes via a reviewed ``git mv``. Either way the
canonical boundary stays human-gated — the gate only chooses *where* that review
happens. The resolved gate is persisted to ``metatron.toml`` so later runs and
the installed skills agree with the generated contract.

Idempotent: safe to run repeatedly; existing AGENTS.md content outside the managed
markers and hand-authored knowledge-base files are preserved. Monorepos: run once
per app dir; workspace-root artifacts (``.roo/``, root AGENTS.md) are shared, the
knowledge base is per-app.

The METATRON markers are the idempotence key shared with
``metatron_setup_files.sh``: either entry point recognizes (and refreshes rather
than duplicates) a block the other one wrote.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from metatron.config import (
    DEFAULT_CONTEXT_DIR,
    DEFAULT_REVIEW_GATE,
    REVIEW_GATES,
    load_settings,
    update_settings,
)

_SKILLS = ("context-okf-llm-ingest", "context-okf-promote-candidates")

_BLOCK_RE = re.compile(r"<!-- METATRON:START.*?METATRON:END -->\n?", re.DOTALL)

_RULE_TEXT = {
    "candidates": """\
# Metatron conventions (files-first)

This repo's coding conventions ("decisions") live as Open Knowledge Format markdown
under `{kb}/`: `{kb}/decisions/` is **canonical**, `{kb}/candidate/` is
**proposed** (unreviewed). In a monorepo each app has its own `{kb}/` — use the
one **nearest** the files you are touching (walk up to the closest `{kb}/`).

- **Consult first.** Before exploring or editing code in an area, read the relevant
  files in the nearest `{kb}/decisions/` and follow them. Say that you did; do
  not rediscover conventions manually until you have. **Only `decisions/` is
  authoritative** — never treat `{kb}/candidate/` content as a convention to
  follow; candidates are unreviewed proposals.
- **Record gaps as candidates.** Found a durable convention that isn't captured?
  Author it as a new OKF file in the nearest `{kb}/candidate/` (skill:
  `context-okf-llm-ingest`). Candidates are proposals for human review — never canonical.
  Refining an *existing* decision? Propose an edit to that file in
  `{kb}/decisions/` on a reviewed branch instead of authoring an overlapping
  candidate.
- **Never self-promote.** Do not move files into `{kb}/decisions/`. Promotion is
  human-gated: a person `git mv`s the file in a reviewed pull request (skill:
  `context-okf-promote-candidates`). Nothing self-promotes.
""",
    "pr": """\
# Metatron conventions (files-first)

This repo's coding conventions ("decisions") live as Open Knowledge Format markdown
under `{kb}/decisions/`. In a monorepo each app has its own `{kb}/` — use the
one **nearest** the files you are touching (walk up to the closest `{kb}/`).

This repo's review gate is **`pr`** (`review_gate` in `metatron.toml`): decisions
are authored directly under `decisions/` on a working branch, and the repository's
ordinary pull-request review is the human curation act.

- **Consult first.** Before exploring or editing code in an area, read the relevant
  files in the nearest `{kb}/decisions/` and follow them. Say that you did; do
  not rediscover conventions manually until you have.
- **Record gaps as decisions — on a branch.** Found a durable convention that isn't
  captured? Author it as a new OKF file in the nearest `{kb}/decisions/` on your
  working branch (skill: `context-okf-llm-ingest`). It reaches the default branch
  only through a human-reviewed pull request — never push decision changes to the
  default branch directly. Refining an existing decision? Edit that file on the
  same terms.
- **Optional staging.** `{kb}/candidate/` remains available for proposals you are
  not ready to put in front of a reviewer; content there is never authoritative
  (skill: `context-okf-promote-candidates` covers moving staged files onward).
""",
}

_KB_README = {
    "candidates": """\
# Metatron knowledge base

Open Knowledge Format (OKF) decisions for this app/repo.

- `decisions/` — **canonical** conventions (human-curated). Agents read these first.
- `candidate/` — **proposed** conventions awaiting human review.

Promotion is human-gated: a reviewer `git mv`s a file from `candidate/` to
`decisions/` in a pull request. Rebuild the (optional) serving index with
`metatron mirror import --root .` run from this directory's parent.
""",
    "pr": """\
# Metatron knowledge base

Open Knowledge Format (OKF) decisions for this app/repo.

- `decisions/` — **canonical** conventions (human-curated). Agents read these first.
- `candidate/` — optional staging for proposals not yet ready for review.

This repo's review gate is `pr`: decisions are authored directly under
`decisions/` on a working branch, and the pull request that lands them is the
human curation act. Never merge decision changes to the default branch without
review. Rebuild the (optional) serving index with
`metatron mirror import --root .` run from this directory's parent.
""",
}

_CONTEXT_MD = {
    "candidates": """\
# Repository Context

## Intent
_Fill this in: one short paragraph on what this project is and the design
philosophy that tiebreaks open decisions. Agents read it before planning._

## Constraints
- Binding conventions for this repository live as one decision per file under
  `{kb}/decisions/` (Open Knowledge Format). Consult the relevant files there
  before planning or modifying code; they are part of this context.
- Files under `{kb}/candidate/` are unreviewed proposals — never treat them
  as binding.

## Evolved Context
<!-- Dated, temporal observations only ([YYYY-MM-DD] observation) — facts that
     will age out, like a pinned version or an environment quirk. Append, never
     rewrite or reorder. New conventions belong in {kb}/candidate/ as decision
     files; refinements of an existing decision are proposed as a reviewed edit
     to that file in {kb}/decisions/. Durable ledger entries get promoted the
     same way. -->
""",
    "pr": """\
# Repository Context

## Intent
_Fill this in: one short paragraph on what this project is and the design
philosophy that tiebreaks open decisions. Agents read it before planning._

## Constraints
- Binding conventions for this repository live as one decision per file under
  `{kb}/decisions/` (Open Knowledge Format). Consult the relevant files there
  before planning or modifying code; they are part of this context.
- Decision files are authored and edited on working branches and land only via
  human-reviewed pull requests (review gate: `pr`).

## Evolved Context
<!-- Dated, temporal observations only ([YYYY-MM-DD] observation) — facts that
     will age out, like a pinned version or an environment quirk. Append, never
     rewrite or reorder. New conventions belong in {kb}/decisions/ as decision
     files authored on a working branch and landed via a reviewed pull request;
     refinements of an existing decision are proposed the same way. -->
""",
}

_ROOT_BLOCK = {
    "candidates": """\
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
a new OKF file in the nearest `{kb}/candidate/` (see the `context-okf-llm-ingest` skill in
`.roo/skills/`). Candidates are uncurated proposals for human review.

**Promotion to canonical is human-gated.** Never move a file into `{kb}/decisions/`
yourself; a human does that via `git mv` reviewed in a pull request (see the
`context-okf-promote-candidates` skill). Nothing self-promotes.
<!-- METATRON:END -->
""",
    "pr": """\
<!-- METATRON:START (managed by metatron context setup — safe to edit inside) -->
## Codebase conventions via Metatron (files) — consult FIRST

This repo's conventions ("decisions") live as Open Knowledge Format markdown under
`{kb}/decisions/`. In a monorepo each app has its own `{kb}/`; use the one
**nearest** the files you are touching.

**Before you Read, Grep, Glob, or Edit code in an area — and before proposing an
implementation — first read the relevant files in the nearest `{kb}/decisions/`
and follow them.** State that you consulted them; do not rediscover conventions
manually until you have.

When you find a durable convention not already captured, **author it as a decision
on your working branch**: a new OKF file in the nearest `{kb}/decisions/` (see the
`context-okf-llm-ingest` skill in `.roo/skills/`). The review gate is `pr`: the
human review of your pull request is the curation act, so decision changes reach
the default branch only through a reviewed PR — never push them there directly.
`{kb}/candidate/` remains available as optional staging for proposals not yet
ready for review; content there is never authoritative.
<!-- METATRON:END -->
""",
}

_APP_BLOCK = {
    "candidates": """\
<!-- METATRON:START (managed by metatron context setup — safe to edit inside) -->
## Metatron conventions for this app — consult FIRST

This app's conventions live in `{kb}/` here: `{kb}/decisions/` (canonical),
`{kb}/candidate/` (proposed). Read the relevant `{kb}/decisions/` before
editing this app's code and follow them; record any missing durable convention as a
candidate OKF file in `{kb}/candidate/`. Never self-promote into
`{kb}/decisions/` — promotion is human-gated via `git mv` in a reviewed pull
request. See the workspace-root `.roo/skills/` (`context-okf-llm-ingest`,
`context-okf-promote-candidates`) for the file format and workflow.
<!-- METATRON:END -->
""",
    "pr": """\
<!-- METATRON:START (managed by metatron context setup — safe to edit inside) -->
## Metatron conventions for this app — consult FIRST

This app's conventions live in `{kb}/decisions/` here. Read the relevant
`{kb}/decisions/` before editing this app's code and follow them. Record any
missing durable convention as a new OKF decision file in `{kb}/decisions/` on
your working branch — the review gate is `pr`, so the human-reviewed pull request
that lands it is the curation act; never push decision changes to the default
branch directly. `{kb}/candidate/` is optional staging (never authoritative). See
the workspace-root `.roo/skills/` (`context-okf-llm-ingest`,
`context-okf-promote-candidates`) for the file format and workflow.
<!-- METATRON:END -->
""",
}

# Injected into the installed skill copies (never the packaged sources) right
# after the frontmatter when the repo's gate is ``pr``, so the skills' default
# candidates-first instructions carry the repo's standing policy with them.
_SKILL_GATE_NOTE = """\

> **Repo review gate: `pr` (configured).** This repository sets
> `review_gate = "pr"` in `metatron.toml` (via `metatron context setup
> --review-gate=pr`): authored decisions go **directly to `decisions/`** on a
> working branch as the standing policy, so treat the explicit human direction
> required by "Where to write" as given repo-wide. The other safeguard still
> applies to every batch: the files may reach the default branch **only through a
> human-reviewed pull request** — no direct pushes, no auto-merge, no bot
> approval. `candidate/` remains available as optional staging.
"""


@dataclass
class SetupResult:
    """What ``run_setup`` did, one human-readable line per artifact."""
    messages: list[str] = field(default_factory=list)
    review_gate: str = DEFAULT_REVIEW_GATE


def _workspace_root(target: Path) -> Path:
    """The git toplevel containing *target*, or *target* itself outside git.

    Root-level artifacts (``.roo/``, the general AGENTS.md block) are shared across
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


def _skill_text(src: Path, kb_name: str, gate: str) -> str:
    """The packaged skill text, adapted to the repo's KB dir and review gate.

    The packaged documents describe the default ``context/`` layout and the
    candidates-first flow. Path references are substituted for a custom KB dir
    (command and product names never contain a trailing slash, so they are
    untouched), and a ``pr``-gate repo gets the standing-policy note injected
    right after the frontmatter.
    """
    text = src.read_text(encoding="utf-8")
    if kb_name != DEFAULT_CONTEXT_DIR:
        text = (
            text.replace("context/candidate", f"{kb_name}/candidate")
                .replace("context/decisions", f"{kb_name}/decisions")
                .replace("`context/`", f"`{kb_name}/`")
                .replace("<repo>/context/", f"<repo>/{kb_name}/")
        )
    if gate == "pr":
        close = text.find("\n---", 3)
        if text.startswith("---") and close != -1:
            insert_at = text.index("\n", close + 1) + 1
            text = text[:insert_at] + _SKILL_GATE_NOTE + text[insert_at:]
    return text


def _write_rule(root: Path, kb_name: str, gate: str, res: SetupResult) -> None:
    rules = root / ".roo" / "rules"
    rules.mkdir(parents=True, exist_ok=True)
    (rules / "metatron.md").write_text(
        _RULE_TEXT[gate].format(kb=kb_name), encoding="utf-8")
    res.messages.append(f"wrote {rules / 'metatron.md'} (review gate: {gate})")


def _install_skills(root: Path, kb_name: str, gate: str, res: SetupResult) -> None:
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
            _skill_text(src / "SKILL.md", kb_name, gate), encoding="utf-8")
    res.messages.append(f"installed skills to {dest_root} ({', '.join(_SKILLS)})")


def _scaffold_kb(target: Path, kb_name: str, gate: str, res: SetupResult) -> None:
    kb = target / kb_name
    for status_dir in ("candidate", "decisions"):
        d = kb / status_dir
        d.mkdir(parents=True, exist_ok=True)
        keep = d / ".gitkeep"
        if not keep.exists():
            keep.touch()
    readme = kb / "README.md"
    text = _KB_README[gate]
    if not readme.exists():
        readme.write_text(text, encoding="utf-8")
        res.messages.append(f"scaffolded {kb} (candidate/, decisions/, README.md)")
        return
    current = readme.read_text(encoding="utf-8")
    if not current.startswith("# Metatron knowledge base"):
        # A hand-replaced README is never overwritten; only the managed one
        # (recognized by its header) is refreshed so a gate change propagates.
        res.messages.append(f"{readme} is hand-authored — left as is")
    elif current != text:
        readme.write_text(text, encoding="utf-8")
        res.messages.append(f"refreshed {readme} (review gate: {gate})")
    else:
        res.messages.append(f"{kb} already scaffolded — left as is")


def _scaffold_context_md(root: Path, kb_name: str, gate: str, res: SetupResult) -> None:
    """Write a minimal Repository Context Layer entry point (``context.md``).

    Gives RCL-conformant agents deterministic discovery: the file carries the
    required Intent/Constraints/Evolved Context sections and points into the
    sharded knowledge base. Never touches an existing context file (either
    discovery form) — it is hand-maintained after creation.
    """
    for existing in (root / "context.md", root / ".repo" / "context.md"):
        if existing.exists():
            res.messages.append(f"{existing} already exists — left as is")
            return
    out = root / "context.md"
    out.write_text(_CONTEXT_MD[gate].format(kb=kb_name), encoding="utf-8")
    res.messages.append(f"wrote {out} (Repository Context Layer entry point)")


def _upsert_agents_block(md: Path, block: str, res: SetupResult) -> None:
    """Append the managed block, or refresh an existing one in place.

    Content outside the METATRON markers is never touched. Refreshing (rather
    than skipping) an existing block is what lets a re-run with a different
    review gate update the contract.
    """
    if md.exists():
        text = md.read_text(encoding="utf-8")
        match = _BLOCK_RE.search(text)
        if match:
            if match.group(0).rstrip("\n") == block.rstrip("\n"):
                res.messages.append(f"{md} already has the Metatron block — left as is")
            else:
                md.write_text(
                    text[:match.start()] + block + text[match.end():],
                    encoding="utf-8")
                res.messages.append(f"updated Metatron block in {md}")
            return
    with md.open("a", encoding="utf-8") as f:
        f.write("\n" + block)
    res.messages.append(f"appended Metatron block to {md}")


def run_setup(target: Path, dir_name: str | None = None,
              review_gate: str | None = None) -> SetupResult:
    """Onboard *target* (a repo or one app of a monorepo) to files-first mode.

    *dir_name* names the knowledge-base directory; when omitted it resolves via
    the ``context_dir`` setting (env/``metatron.toml``), defaulting to ``context``.
    *review_gate* picks where humans review agent-authored decisions (see
    ``config.REVIEW_GATES``); when omitted it resolves via the ``review_gate``
    setting, defaulting to ``pr``. The resolved gate is persisted to the
    workspace-root ``metatron.toml`` so later runs and the installed artifacts
    stay in agreement.
    """
    target = target.resolve()
    root = _workspace_root(target)
    settings = load_settings(root / "metatron.toml")
    kb_name = dir_name or settings.context_dir or DEFAULT_CONTEXT_DIR
    gate = review_gate or settings.review_gate or DEFAULT_REVIEW_GATE
    if gate not in REVIEW_GATES:
        raise ValueError(
            f"unknown review gate {gate!r} (expected one of: {', '.join(REVIEW_GATES)})")
    res = SetupResult(review_gate=gate)
    if gate != settings.review_gate:
        update_settings({"review_gate": gate}, path=root / "metatron.toml")
        res.messages.append(
            f'persisted review_gate = "{gate}" to {root / "metatron.toml"}')
    _write_rule(root, kb_name, gate, res)
    _install_skills(root, kb_name, gate, res)
    _scaffold_kb(target, kb_name, gate, res)
    _scaffold_context_md(root, kb_name, gate, res)
    _upsert_agents_block(root / "AGENTS.md", _ROOT_BLOCK[gate].format(kb=kb_name), res)
    if target != root:
        _upsert_agents_block(target / "AGENTS.md", _APP_BLOCK[gate].format(kb=kb_name), res)
    return res
