"""DB → git-tracked bundle. Deterministic: re-running with no DB change is a no-op.

Rejected decisions are NOT mirrored (so rejected content can't be re-promoted by
moving a file). Writes a `.sync-state.json` of per-id content hashes for the
importer's collision detection.
"""
from __future__ import annotations

import json
from pathlib import Path
from metatron.config import resolve_context_dir
from metatron.models import Status
from metatron.feedback_score import helpfulness_scores
from metatron.mirror.render import render_document, fingerprint_decision
from metatron.mirror.layout import path_for

def export_bundle(store, repo: str, root: Path, events: list,
                  context_dir: str | None = None) -> dict[str, str]:
    mirror = resolve_context_dir(root, context_dir)
    scores = helpfulness_scores(events)
    state: dict[str, str] = {}
    written: set[Path] = set()
    for status in (Status.CANDIDATE, Status.CANONICAL):
        for d in store.list(repo=repo, status=status):
            text = render_document(d, helpfulness=scores.get(d.id))
            dest = path_for(d, mirror)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(text)
            written.add(dest.resolve())
            # Baseline is the human-field fingerprint (not the full text), so it is
            # directly comparable to the importer's fingerprints and immune to drift
            # in machine-owned fields (helpfulness_score, updated_at).
            state[d.id] = fingerprint_decision(d)
    # Make the export a true DB -> files mirror: a decision that left the exported
    # set (demoted, rejected, deleted) must not leave a stale file behind. Prune
    # is confined to the two status dirs and never touches index.md, the sync
    # state, or anything outside them.
    for status_dir in ("candidate", "decisions"):
        for stale in (mirror / status_dir).glob("*.md"):
            if stale.resolve() not in written:
                stale.unlink()
    state_path = mirror / ".sync-state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=2, sort_keys=True))
    return state
