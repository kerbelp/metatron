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
    updated: list = field(default_factory=list)
    promoted: list = field(default_factory=list)
    conflicts: list = field(default_factory=list)
    warnings: list = field(default_factory=list)


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
    for path in sorted(mirror.rglob("*.md")):
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
        baseline = state.get(did)
        file_fp = fingerprint_fields(fields, status)
        db_fp = fingerprint_decision(decision)
        file_changed = baseline is None or file_fp != baseline
        db_changed = baseline is not None and db_fp != baseline
        if file_changed and db_changed and file_fp != db_fp:
            res.conflicts.append(did)
            continue
        if not file_changed:
            continue
        if decision.status != status:
            store.set_status(did, status)
            res.promoted.append(did)
        updates = {}
        if fields.get("pattern") and fields["pattern"] != decision.pattern:
            updates["pattern"] = fields["pattern"]
        if fields.get("rationale") and fields["rationale"] != decision.rationale:
            updates["rationale"] = fields["rationale"]
        if fields.get("scope") and fields["scope"] != decision.scope:
            updates["scope"] = fields["scope"]
        if fields.get("confidence") and fields["confidence"] != decision.confidence.value:
            updates["confidence"] = Confidence(fields["confidence"])
        if updates:
            store.update_fields(did, **updates)
            res.updated.append(did)
    return res
