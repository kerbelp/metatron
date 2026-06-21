from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

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
