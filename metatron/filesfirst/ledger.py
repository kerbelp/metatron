from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from metatron.filesfirst.trailers import parse_trailers

_SHARD_HEADER = (
    "# Usage ledger\n\n"
    "> CI-written, append-only. Not a decision — excluded from review.\n\n"
    "| date | sha | decision | kind |\n|---|---|---|---|\n"
)
_UNMATCHED_HEADER = (
    "# Unmatched decision IDs (quarantine)\n\n"
    "> Declared in a trailer but no matching decision file. Excluded from counts.\n\n"
    "| date | sha | decision | kind |\n|---|---|---|---|\n"
)


@dataclass(frozen=True)
class LedgerEntry:
    date: str          # ISO date (YYYY-MM-DD)
    sha: str
    decision_id: str
    kind: str          # applied | considered | violated

    def row(self) -> str:
        return f"| {self.date} | `{self.sha}` | {self.decision_id} | {self.kind} |"

    def key(self) -> tuple[str, str, str]:
        return (self.sha, self.decision_id, self.kind)


def read_entries(shard: Path) -> list[LedgerEntry]:
    """Parse a shard's table rows back into entries (ignores header/blank lines)."""
    if not shard.exists():
        return []
    out: list[LedgerEntry] = []
    for line in shard.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| ") or "---" in line or "| date " in line:
            continue
        cells = [c.strip().strip("`") for c in line.strip().strip("|").split("|")]
        if len(cells) != 4:
            continue
        date, sha, decision_id, kind = cells
        out.append(LedgerEntry(date=date, sha=sha, decision_id=decision_id, kind=kind))
    return out


def _append(shard: Path, header: str, entries: list[LedgerEntry]) -> None:
    if not entries:
        return
    shard.parent.mkdir(parents=True, exist_ok=True)
    seen = {e.key() for e in read_entries(shard)}
    fresh = [e for e in entries if e.key() not in seen]
    if not fresh:
        return
    existing = shard.read_text(encoding="utf-8") if shard.exists() else header
    shard.write_text(
        existing + "\n".join(e.row() for e in fresh) + "\n", encoding="utf-8")


def append_entries(
    log_dir: Path, entries: list[LedgerEntry], *, known_ids: set[str]
) -> None:
    """Append matched entries to their month shard; quarantine unmatched IDs."""
    log_dir = Path(log_dir)
    matched_by_month: dict[str, list[LedgerEntry]] = {}
    unmatched: list[LedgerEntry] = []
    for e in entries:
        if e.decision_id in known_ids:
            matched_by_month.setdefault(e.date[:7], []).append(e)
        else:
            unmatched.append(e)
    for month, month_entries in matched_by_month.items():
        _append(log_dir / f"{month}.md", _SHARD_HEADER, month_entries)
    _append(log_dir / "unmatched.md", _UNMATCHED_HEADER, unmatched)


def entries_from_commit(commit) -> list[LedgerEntry]:
    """Expand a commit's trailers into ledger entries (duck-typed: needs
    `.sha`, `.date` (datetime), `.body`)."""
    t = parse_trailers(commit.body)
    day = commit.date.date().isoformat()
    entries: list[LedgerEntry] = []
    for kind, ids in (
        ("applied", t.applied), ("considered", t.considered), ("violated", t.violated)
    ):
        for decision_id in ids:
            entries.append(
                LedgerEntry(date=day, sha=commit.sha, decision_id=decision_id, kind=kind))
    return entries
