from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from metatron.mirror.render import split_frontmatter


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
