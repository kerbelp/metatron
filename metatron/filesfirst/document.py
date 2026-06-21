from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml
from metatron.mirror.render import split_frontmatter
from metatron.filesfirst.schema import RESERVED_FILENAMES


@dataclass
class DecisionFile:
    path: Path
    frontmatter: dict
    body: str

    @property
    def id(self) -> str | None:
        return self.frontmatter.get("id")

    @property
    def status(self) -> str | None:
        return self.frontmatter.get("status")


def parse_decision_file(path: Path, text: str) -> DecisionFile:
    """Parse one OKF decision file's text into frontmatter + body."""
    frontmatter, body = split_frontmatter(text)
    return DecisionFile(path=path, frontmatter=frontmatter or {}, body=body)


def decision_ids(decisions_dir: Path) -> set[str]:
    """The set of decision IDs declared in a tree (reserved files skipped)."""
    ids: set[str] = set()
    for md in Path(decisions_dir).glob("*.md"):
        if md.name in RESERVED_FILENAMES:
            continue
        doc = parse_decision_file(md, md.read_text(encoding="utf-8"))
        if doc.id:
            ids.add(doc.id)
    return ids


def _is_top_level_key(line: str, keys) -> bool:
    """True if ``line`` is a top-level ``key:`` entry for one of ``keys``.

    Indented lines (block-list items, nested values) are never matched, so only
    the scalar machine-field lines are replaced — human-authored formatting is
    left byte-for-byte intact.
    """
    if not line or line[0].isspace() or ":" not in line:
        return False
    return line.split(":", 1)[0].strip() in keys


def write_machine_fields(path: Path, fields: dict) -> None:
    """Merge machine-owned fields into a decision file's frontmatter in place.

    Only the machine-field lines are rewritten (replaced if present, else
    appended); every human-authored frontmatter line and the prose body are
    preserved verbatim, so a CI count update never reflows lines it does not own.
    """
    text = Path(path).read_text(encoding="utf-8")
    _, sep, rest = text.partition("---\n")
    if not sep:
        return  # no frontmatter block to update
    front_raw, _, body = rest.partition("\n---\n")
    kept = [
        line for line in front_raw.splitlines()
        if not _is_top_level_key(line, fields)
    ]
    for key, value in fields.items():
        kept.append(yaml.safe_dump({key: value}, sort_keys=False).strip())
    Path(path).write_text("---\n" + "\n".join(kept) + "\n---\n" + body, encoding="utf-8")
