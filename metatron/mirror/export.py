"""DB → git-tracked bundle. Deterministic: re-running with no DB change is a no-op.

Rejected decisions are NOT mirrored (so rejected content can't be re-promoted by
moving a file). Writes a `.sync-state.json` of per-id content hashes for the
importer's collision detection.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from metatron.models import Status
from metatron.feedback_score import helpfulness_scores
from metatron.mirror.render import render_document
from metatron.mirror.layout import path_for

def export_bundle(store, repo: str, root: Path, events: list) -> dict[str, str]:
    scores = helpfulness_scores(events)
    state: dict[str, str] = {}
    for status in (Status.CANDIDATE, Status.CANONICAL):
        for d in store.list(repo=repo, status=status):
            text = render_document(d, helpfulness=scores.get(d.id))
            dest = root / path_for(d)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(text)
            state[d.id] = hashlib.sha1(text.encode("utf-8")).hexdigest()
    state_path = root / "metatron" / ".sync-state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=2, sort_keys=True))
    return state
