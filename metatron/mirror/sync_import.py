"""Bundle -> DB. Directory sets status; only human-owned fields apply; machine
fields are ignored (warned); concurrent DB+file edits are surfaced, not clobbered.
"""
from __future__ import annotations

import json
from datetime import datetime
from dataclasses import dataclass, field
from pathlib import Path

from metatron.models import (
    Confidence, Decision, Origin, SourceRef, SourceRefKind,
)
from metatron.mirror.render import (
    parse_document, fingerprint_decision, fingerprint_fields, split_frontmatter,
)
from metatron.mirror.layout import status_for_path
from metatron.filesfirst.schema import RESERVED_FILENAMES


@dataclass
class ImportResult:
    updated: list[str] = field(default_factory=list)
    promoted: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _raw_frontmatter(text: str) -> dict:
    fm, _ = split_frontmatter(text)
    return fm


def _timestamp_edited(raw_value, db_value: datetime) -> bool:
    """True only if a read-only timestamp was actually changed.

    ``yaml.safe_load`` parses an unquoted ISO timestamp into a ``datetime`` whose
    ``str()`` uses a space (not ``T``); comparing that string to ``isoformat()``
    would falsely flag an unedited value. Compare ``datetime`` objects directly
    when possible, and fall back to normalized-string comparison otherwise.
    """
    if isinstance(raw_value, datetime):
        return raw_value != db_value
    return str(raw_value) != db_value.isoformat()


def import_bundle(store, repo: str, root: Path) -> ImportResult:
    res = ImportResult()
    mirror = root / "metatron"
    state = {}
    state_path = mirror / ".sync-state.json"
    if state_path.exists():
        state = json.loads(state_path.read_text())
    # Only files directly inside the two status directories are mirror
    # documents; any other .md under metatron/ (e.g. a README) is ignored.
    paths = sorted((mirror / "candidate").glob("*.md")) + \
        sorted((mirror / "decisions").glob("*.md"))
    for path in paths:
        # Generated listings (index.md, log.md) live in the status directories
        # but are not concept documents — never import them.
        if path.name in RESERVED_FILENAMES:
            continue
        text = path.read_text()
        fields = parse_document(text)
        did = fields.get("id")
        decision = store.get(did) if did else None
        status = status_for_path(path)
        if did is None:
            # An id-less file must declare itself an OKF concept; anything else
            # (a stray note, a misplaced README) must not silently become a
            # decision at the directory-derived status.
            if not str(_raw_frontmatter(text).get("type") or "").strip():
                res.warnings.append(
                    f"{path.name}: no 'type' frontmatter — not a decision document, skipped"
                )
                continue
            # Hand-authored file with no id: the human placing it in this
            # directory IS the approval, so create the decision at the
            # directory-derived status. source_refs is honored at authoring
            # (it is read-only only on later edits of an existing decision).
            source_refs = [
                SourceRef(kind=SourceRefKind.FILE, ref=str(ref))
                for ref in (fields.get("source_refs") or [])
            ]
            new = Decision(
                repo=repo,
                pattern=fields.get("pattern", ""),
                scope=fields.get("scope", ""),
                rationale=fields.get("rationale", ""),
                origin=Origin.HUMAN,
                status=status,
                confidence=Confidence(fields["confidence"]) if fields.get("confidence") else Confidence.MEDIUM,
                source_refs=source_refs,
            )
            created = store.add(new)
            res.updated.append(created.id)
            continue
        if decision is None:
            # File carries an id we don't know (e.g. copied from another repo).
            # Do not mint a decision under a foreign identity; surface it.
            res.warnings.append(f"{did}: unknown decision id; skipped.")
            continue
        if decision.repo != repo:
            # The id resolves (a shared/catalog store finds it cross-repo), but it
            # belongs to a different repo. Editing/promoting it under this repo
            # would corrupt the wrong repo's curation; skip and surface it.
            res.warnings.append(f"{did}: belongs to a different repo; skipped.")
            continue
        # machine-field guard: warn if read-only frontmatter was edited
        raw = _raw_frontmatter(text)
        if "keywords" in raw and list(raw["keywords"]) != list(decision.keywords):
            res.warnings.append(
                f"{did}: 'keywords' is read-only (machine-derived); ignored."
            )
        if "created_at" in raw and _timestamp_edited(raw["created_at"], decision.created_at):
            res.warnings.append(
                f"{did}: 'created_at' is read-only (machine-derived); ignored."
            )
        if "updated_at" in raw and _timestamp_edited(raw["updated_at"], decision.updated_at):
            res.warnings.append(
                f"{did}: 'updated_at' is read-only (machine-derived); ignored."
            )
        baseline = state.get(did)
        file_fp = fingerprint_fields(fields, status)
        db_fp = fingerprint_decision(decision)
        if baseline is None:
            # No sync baseline: we cannot tell which side moved. If file and DB
            # already agree there's nothing to apply; if they differ, surface a
            # conflict rather than blindly letting the file win.
            if file_fp != db_fp:
                res.conflicts.append(did)
                res.warnings.append(
                    f"{did}: no sync baseline; DB and file differ — not applied "
                    f"(run 'mirror sync' first)."
                )
            continue
        file_changed = file_fp != baseline
        db_changed = db_fp != baseline
        if file_changed and db_changed and file_fp != db_fp:
            res.conflicts.append(did)
            continue
        if not file_changed:
            continue
        if decision.status != status:
            store.set_status(did, status)
            res.promoted.append(did)
        updates = {}
        # Compare by presence + inequality (not truthiness) so a deliberate
        # clearing of a human field ("" vs old value) still applies.
        for fname in ("pattern", "rationale", "scope"):
            if fname in fields and fields[fname] != getattr(decision, fname):
                updates[fname] = fields[fname]
        # Confidence keeps the truthiness guard: an empty confidence is invalid
        # and must not wipe the enum.
        if fields.get("confidence") and fields["confidence"] != decision.confidence.value:
            updates["confidence"] = Confidence(fields["confidence"])
        if updates:
            store.update_fields(did, **updates)
            res.updated.append(did)
    return res
