from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from metatron.filesfirst.document import DecisionFile, parse_decision_file
from metatron.filesfirst.schema import (
    CONFIDENCE,
    REQUIRED_FIELDS,
    RESERVED_FILENAMES,
    STATUSES,
)


@dataclass(frozen=True)
class LintError:
    path: Path
    message: str


def lint_decision(doc: DecisionFile) -> list[LintError]:
    errs: list[LintError] = []
    fm = doc.frontmatter
    for field_name in REQUIRED_FIELDS:
        if not fm.get(field_name):
            errs.append(LintError(doc.path, f"missing required field: {field_name}"))
    status = fm.get("status")
    if status is not None and status not in STATUSES:
        errs.append(LintError(
            doc.path, f"invalid status: {status!r} (allowed: {', '.join(STATUSES)})"))
    confidence = fm.get("confidence")
    if confidence is not None and confidence not in CONFIDENCE:
        errs.append(LintError(doc.path, f"invalid confidence: {confidence!r}"))
    slug = doc.path.stem
    if fm.get("id") and fm["id"] != slug:
        errs.append(LintError(
            doc.path, f"id {fm['id']!r} must match filename slug {slug!r}"))
    return errs


def lint_tree(decisions_dir: Path) -> list[LintError]:
    errs: list[LintError] = []
    seen: dict[str, Path] = {}
    for md in sorted(Path(decisions_dir).glob("*.md")):
        if md.name in RESERVED_FILENAMES:
            continue
        doc = parse_decision_file(md, md.read_text(encoding="utf-8"))
        errs.extend(lint_decision(doc))
        decision_id = doc.id
        if decision_id:
            if decision_id in seen:
                errs.append(LintError(
                    md, f"duplicate id {decision_id!r} (also {seen[decision_id].name})"))
            else:
                seen[decision_id] = md
    return errs
