"""Bundle -> DB. Directory sets status; only human-owned fields apply; machine
fields are ignored (warned); concurrent DB+file edits are surfaced, not clobbered.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from metatron.models import Status, Confidence
from metatron.mirror.render import (
    parse_document, fingerprint_decision, fingerprint_fields,
)
from metatron.mirror.layout import status_for_path


@dataclass
class ImportResult:
    updated: list[str] = field(default_factory=list)
    promoted: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _raw_frontmatter(text: str) -> dict:
    _, _, rest = text.partition("---\n")
    front_raw, _, _ = rest.partition("\n---\n")
    return yaml.safe_load(front_raw) or {}


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
        text = path.read_text()
        fields = parse_document(text)
        did = fields.get("id")
        decision = store.get(did) if did else None
        status = status_for_path(path)
        if decision is None:
            continue  # new-file authoring handled in a later task
        # machine-field guard: warn if read-only frontmatter was edited
        raw = _raw_frontmatter(text)
        if "keywords" in raw and list(raw["keywords"]) != list(decision.keywords):
            res.warnings.append(
                f"{did}: 'keywords' is read-only (machine-derived); ignored."
            )
        if "created_at" in raw and str(raw["created_at"]) != decision.created_at.isoformat():
            res.warnings.append(
                f"{did}: 'created_at' is read-only (machine-derived); ignored."
            )
        if "updated_at" in raw and str(raw["updated_at"]) != decision.updated_at.isoformat():
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
