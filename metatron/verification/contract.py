"""Parse a verification-contract markdown file into a structured object.

The parser keys off ``## `` section headings and ``### `` check headings; bodies
stay human-readable and diff-friendly. Nothing here executes — see ``runner``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from metatron.mirror.render import split_frontmatter
from metatron.verification.schema import (
    SECTION_ASSUMPTIONS,
    SECTION_CHECKS,
    SECTION_FAILURE_MEANS,
    SECTION_JUDGED,
    SECTION_SETUP,
    SECTION_TEARDOWN,
)

_TAGS_RE = re.compile(r"\[tags:\s*([^\]]*)\]", re.IGNORECASE)


@dataclass
class Assertion:
    """One `Expect:` line, parsed into an evaluable form.

    ``kind`` is one of the deterministic ASSERTION_KINDS, or ``"invalid"`` when
    the line could not be parsed (audit flags these; the runner fails them).
    """
    raw: str
    kind: str
    # kind-specific payload
    stream: str | None = None      # "stdout" | "stderr" for contains/matches
    text: str | None = None        # substring / regex / shell command / jsonpath
    code: int | None = None        # expected exit code
    path: str | None = None        # jsonpath expression
    op: str | None = None          # "==" | "exists"
    value: str | None = None       # expected jsonpath value (raw token)


@dataclass
class Check:
    name: str
    tags: list[str] = field(default_factory=list)
    action: str = ""               # shell script (may be multi-line)
    expects: list[Assertion] = field(default_factory=list)


@dataclass
class VerificationContract:
    path: Path
    frontmatter: dict
    assumptions: list[str] = field(default_factory=list)
    setup: str = ""                # shell script
    checks: list[Check] = field(default_factory=list)
    failure_means: list[str] = field(default_factory=list)
    judged: list[str] = field(default_factory=list)   # phase-2 LLM invariants
    teardown: str = ""             # shell script

    @property
    def scope(self) -> str:
        return str(self.frontmatter.get("scope") or "").strip()

    @property
    def slug(self) -> str:
        return self.path.stem

    def to_dict(self) -> dict:
        """JSON-serializable view for the read-only MCP tool."""
        return {
            "slug": self.slug,
            "scope": self.scope,
            "type": self.frontmatter.get("type"),
            "confidence": self.frontmatter.get("confidence"),
            "source_refs": self.frontmatter.get("source_refs") or [],
            "assumptions": self.assumptions,
            "setup": self.setup,
            "checks": [
                {
                    "name": c.name,
                    "tags": c.tags,
                    "action": c.action,
                    "expects": [a.raw for a in c.expects],
                }
                for c in self.checks
            ],
            "failure_means": self.failure_means,
            "judged": self.judged,
            "teardown": self.teardown,
        }


def _dedent_block(lines: list[str]) -> str:
    """Join a run of indented lines into a script, stripping the common 4-space
    (or tab) code-block indent and dropping surrounding blank lines."""
    out = []
    for ln in lines:
        if ln.startswith("    "):
            out.append(ln[4:])
        elif ln.startswith("\t"):
            out.append(ln[1:])
        elif not ln.strip():
            out.append("")
        else:
            out.append(ln)
    return "\n".join(out).strip("\n")


def _bullets(lines: list[str]) -> list[str]:
    """Collect ``- `` bullets, folding wrapped continuation lines into the bullet."""
    out: list[str] = []
    for ln in lines:
        s = ln.strip()
        if s.startswith("- "):
            out.append(s[2:].strip())
        elif s and out and not ln.startswith("## "):
            out[-1] = f"{out[-1]} {s}"
    return out


def parse_assertion(raw: str) -> Assertion:
    """Parse one `Expect:` bullet into a structured Assertion."""
    s = raw.strip()
    low = s.lower()

    m = re.match(r"exit\s+(-?\d+)$", low)
    if m:
        return Assertion(raw=raw, kind="exit", code=int(m.group(1)))

    m = re.match(r"(?:(stdout|stderr)\s+)?contains\s+(.+)$", s, re.IGNORECASE)
    if m:
        return Assertion(raw=raw, kind="contains",
                         stream=(m.group(1) or "stdout").lower(),
                         text=_unquote(m.group(2)))

    m = re.match(r"(?:(stdout|stderr)\s+)?matches\s+(.+)$", s, re.IGNORECASE)
    if m:
        return Assertion(raw=raw, kind="matches",
                         stream=(m.group(1) or "stdout").lower(),
                         text=_unquote(m.group(2)))

    m = re.match(r"(?:stdout\s+)?jsonpath\s+(\S+)\s+exists$", s, re.IGNORECASE)
    if m:
        return Assertion(raw=raw, kind="jsonpath", path=m.group(1), op="exists")
    m = re.match(r"(?:stdout\s+)?jsonpath\s+(\S+)\s*==\s*(.+)$", s, re.IGNORECASE)
    if m:
        return Assertion(raw=raw, kind="jsonpath", path=m.group(1), op="==",
                         value=_unquote(m.group(2)))

    m = re.match(r"shell\s+(.+)$", s, re.IGNORECASE)
    if m:
        return Assertion(raw=raw, kind="shell", text=m.group(1).strip())

    return Assertion(raw=raw, kind="invalid")


def _unquote(tok: str) -> str:
    tok = tok.strip()
    if len(tok) >= 2 and tok[0] == tok[-1] and tok[0] in "`'\"":
        return tok[1:-1]
    return tok


def _split_sections(body: str) -> dict[str, list[str]]:
    """Group body lines under their ``## `` heading. Preamble before the first
    heading is discarded (contracts lead with sections)."""
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for ln in body.splitlines():
        if ln.startswith("## ") and not ln.startswith("### "):
            # Strip a trailing bracket annotation, e.g. "Judged invariants [--judge]".
            current = re.sub(r"\s*\[[^\]]*\]\s*$", "", ln[3:].strip())
            sections.setdefault(current, [])
        elif current is not None:
            sections[current].append(ln)
    return sections


def _parse_checks(lines: list[str]) -> list[Check]:
    checks: list[Check] = []
    cur: Check | None = None
    mode: str | None = None            # "action" | "expect"
    action_lines: list[str] = []

    def finalize() -> None:
        # Only write the action when we are still collecting it; the `Expect:`
        # marker already committed it, so don't clobber with an emptied buffer.
        if cur is not None and mode == "action":
            cur.action = _dedent_block(action_lines)

    for ln in lines:
        if ln.startswith("### "):
            finalize()
            if cur is not None:
                checks.append(cur)
            header = ln[4:].strip()
            tags: list[str] = []
            tm = _TAGS_RE.search(header)
            if tm:
                tags = [t.strip() for t in tm.group(1).split(",") if t.strip()]
                header = _TAGS_RE.sub("", header).strip()
            cur = Check(name=header, tags=tags)
            mode, action_lines = None, []
            continue
        if cur is None:
            continue
        stripped = ln.strip().lower()
        if stripped == "action:":
            mode = "action"
            continue
        if stripped == "expect:":
            cur.action = _dedent_block(action_lines)
            action_lines = []
            mode = "expect"
            continue
        if mode == "action":
            action_lines.append(ln)
        elif mode == "expect" and ln.strip().startswith("- "):
            cur.expects.append(parse_assertion(ln.strip()[2:]))
    finalize()
    if cur is not None:
        checks.append(cur)
    return checks


def parse_contract(path: Path, text: str) -> VerificationContract:
    frontmatter, body = split_frontmatter(text)
    sections = _split_sections(body or "")
    judged_raw = _bullets(sections.get(SECTION_JUDGED, []))
    judged = [b[len("judge:"):].strip() if b.lower().startswith("judge:") else b
              for b in judged_raw]
    return VerificationContract(
        path=path,
        frontmatter=frontmatter or {},
        assumptions=_bullets(sections.get(SECTION_ASSUMPTIONS, [])),
        setup=_dedent_block(sections.get(SECTION_SETUP, [])),
        checks=_parse_checks(sections.get(SECTION_CHECKS, [])),
        failure_means=_bullets(sections.get(SECTION_FAILURE_MEANS, [])),
        judged=judged,
        teardown=_dedent_block(sections.get(SECTION_TEARDOWN, [])),
    )


def load_contract(path: Path) -> VerificationContract:
    return parse_contract(Path(path), Path(path).read_text(encoding="utf-8"))
