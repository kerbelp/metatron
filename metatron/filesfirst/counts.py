from __future__ import annotations

from pathlib import Path

from metatron.filesfirst.document import write_machine_fields
from metatron.filesfirst.ledger import read_entries


def aggregate(log_dir: Path) -> dict[str, dict]:
    """Aggregate month shards into per-decision derived fields.

    Only `<YYYY-MM>.md` shards are read; `unmatched.md` is excluded by design.
    """
    counts: dict[str, dict] = {}
    for shard in sorted(Path(log_dir).glob("*.md")):
        if shard.name == "unmatched.md":
            continue
        for e in read_entries(shard):
            slot = counts.setdefault(
                e.decision_id, {"references": 0, "violations": 0, "last_applied": None})
            if e.kind == "applied":
                slot["references"] += 1
                if slot["last_applied"] is None or e.date > slot["last_applied"]:
                    slot["last_applied"] = e.date
            elif e.kind == "violated":
                slot["violations"] += 1
    # Drop the null last_applied for decisions only ever considered/violated.
    for slot in counts.values():
        if slot["last_applied"] is None:
            del slot["last_applied"]
    return counts


def apply_counts(decisions_dir: Path) -> dict[str, dict]:
    """Aggregate `<decisions_dir>/log/` and write the derived machine fields
    back into each matching decision file. Returns the aggregate."""
    decisions_dir = Path(decisions_dir)
    agg = aggregate(decisions_dir / "log")
    for decision_id, fields in agg.items():
        target = decisions_dir / f"{decision_id}.md"
        if target.exists():
            write_machine_fields(target, fields)
    return agg
