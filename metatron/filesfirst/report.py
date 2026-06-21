from __future__ import annotations

from collections import Counter
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


@dataclass
class Report:
    start: str
    end: str
    total_commits: int
    consulted_commits: int
    adoption_pct: float
    reuse: list[tuple[str, str, int]]        # (id, title, applied_count), desc
    violations: list[tuple[str, str, str]]   # (id, title, sha)
    status_counts: dict[str, int]
    candidates_awaiting: int


def _title(decisions: dict[str, DecisionMeta], decision_id: str) -> str:
    meta = decisions.get(decision_id)
    return meta.title if meta else ""


def build_report(
    entries: list[LedgerEntry],
    total_commits: int,
    decisions: dict[str, DecisionMeta],
    start: str,
    end: str,
) -> Report:
    """Aggregate windowed ledger entries + decision metadata into a Report."""
    applied = Counter(e.decision_id for e in entries if e.kind == "applied")
    reuse = sorted(
        ((decision_id, _title(decisions, decision_id), count)
         for decision_id, count in applied.items()),
        key=lambda row: (-row[2], row[0]),
    )
    violations = [
        (e.decision_id, _title(decisions, e.decision_id), e.sha)
        for e in entries if e.kind == "violated"
    ]
    consulted = {e.sha for e in entries}
    adoption_pct = round(100 * len(consulted) / total_commits, 1) if total_commits else 0.0
    status_counts = dict(Counter(m.status for m in decisions.values()))
    return Report(
        start=start,
        end=end,
        total_commits=total_commits,
        consulted_commits=len(consulted),
        adoption_pct=adoption_pct,
        reuse=reuse,
        violations=violations,
        status_counts=status_counts,
        candidates_awaiting=status_counts.get("candidate", 0),
    )


def _reuse_section(reuse: list[tuple[str, str, int]], top: int) -> str:
    if not reuse:
        return "_No decisions applied in this window._\n"
    rows = "".join(
        f"| `{decision_id}` | {title} | {count} |\n"
        for decision_id, title, count in reuse[:top])
    return "| decision | title | applied |\n|---|---|---|\n" + rows


def _drift_section(violations: list[tuple[str, str, str]]) -> str:
    if not violations:
        return "_No drift caught in this window._\n"
    rows = "".join(
        f"| `{decision_id}` | {title} | `{sha}` |\n"
        for decision_id, title, sha in violations)
    return "| decision | title | commit |\n|---|---|---|\n" + rows


def _curation_section(status_counts: dict[str, int], awaiting: int) -> str:
    rows = "".join(
        f"| {status} | {status_counts[status]} |\n"
        for status in sorted(status_counts))
    table = "| status | count |\n|---|---|\n" + rows
    return f"{table}\n{awaiting} candidate(s) awaiting promotion.\n"


def render_markdown(report: Report, *, top: int = 10) -> str:
    """Render a Report as a deterministic markdown digest (no dollar figures)."""
    return (
        "# Decision usage digest\n\n"
        f"**Window:** {report.start} to {report.end}\n\n"
        "## Adoption\n\n"
        f"{report.consulted_commits} of {report.total_commits} commits "
        f"({report.adoption_pct}%) consulted a decision.\n\n"
        "## Knowledge reuse\n\n"
        f"{_reuse_section(report.reuse, top)}\n"
        "## Drift caught\n\n"
        f"{_drift_section(report.violations)}\n"
        "## Curation health\n\n"
        f"{_curation_section(report.status_counts, report.candidates_awaiting)}\n"
        "---\n\n"
        "_Every count above traces to a merged commit trailer._\n"
    )
