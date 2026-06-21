from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from metatron.filesfirst.document import parse_decision_file
from metatron.filesfirst.ledger import LedgerEntry, read_entries
from metatron.filesfirst.schema import RESERVED_FILENAMES


@dataclass(frozen=True)
class DecisionMeta:
    id: str
    title: str
    status: str


def load_decisions(decisions_dir: Path) -> dict[str, DecisionMeta]:
    """Map decision id -> (id, title, status) for a tree (reserved files skipped)."""
    metas: dict[str, DecisionMeta] = {}
    for md in sorted(Path(decisions_dir).glob("*.md")):
        if md.name in RESERVED_FILENAMES:
            continue
        fm = parse_decision_file(md, md.read_text(encoding="utf-8")).frontmatter
        decision_id = fm.get("id")
        if decision_id:
            metas[decision_id] = DecisionMeta(
                id=decision_id, title=fm.get("title", ""), status=fm.get("status", ""))
    return metas


def load_window_entries(log_dir: Path, start: str, end: str) -> list[LedgerEntry]:
    """Ledger entries with `start <= date <= end` (inclusive ISO dates).

    Only `<YYYY-MM>.md` shards overlapping the window are read; `unmatched.md`
    is excluded by design.
    """
    out: list[LedgerEntry] = []
    # Ledger shards are named `<YYYY-MM>.md` (see append_entries' month sharding),
    # so a lexical compare of `shard.stem` against the window's months is exact.
    for shard in sorted(Path(log_dir).glob("*.md")):
        if shard.name == "unmatched.md":
            continue
        if not (start[:7] <= shard.stem <= end[:7]):
            continue
        out.extend(e for e in read_entries(shard) if start <= e.date <= end)
    return out
