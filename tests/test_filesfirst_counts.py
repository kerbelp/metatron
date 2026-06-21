from pathlib import Path

from metatron.filesfirst.counts import aggregate, apply_counts
from metatron.filesfirst.ledger import LedgerEntry, append_entries


def _decision(d: Path, slug: str):
    (d / f"{slug}.md").write_text(
        f"---\nid: {slug}\ntype: decision\nstatus: canonical\ntitle: T\n---\nb\n",
        encoding="utf-8")


def test_aggregate_counts_applied_and_violated(tmp_path):
    log = tmp_path / "log"
    append_entries(log, [
        LedgerEntry("2026-06-10", "s1", "d", "applied"),
        LedgerEntry("2026-06-18", "s2", "d", "applied"),
        LedgerEntry("2026-06-12", "s3", "d", "violated"),
        LedgerEntry("2026-06-11", "s4", "d", "considered"),
    ], known_ids={"d"})
    agg = aggregate(log)
    assert agg["d"]["references"] == 2
    assert agg["d"]["violations"] == 1
    assert agg["d"]["last_applied"] == "2026-06-18"   # max applied date
    assert "considered" not in agg["d"]               # not a counted field


def test_apply_counts_writes_fields_into_decisions(tmp_path):
    _decision(tmp_path, "d")
    log = tmp_path / "log"
    append_entries(log, [LedgerEntry("2026-06-18", "s1", "d", "applied")], known_ids={"d"})
    apply_counts(tmp_path)   # path = decisions dir; log/ lives under it
    text = (tmp_path / "d.md").read_text(encoding="utf-8")
    assert "references: 1" in text
    assert "last_applied: '2026-06-18'" in text or "last_applied: 2026-06-18" in text


def test_unmatched_shard_is_excluded_from_aggregate(tmp_path):
    log = tmp_path / "log"
    # 'ghost' is unknown -> goes to unmatched.md, must not appear in the aggregate.
    append_entries(log, [LedgerEntry("2026-06-18", "s1", "ghost", "applied")],
                   known_ids={"real"})
    assert aggregate(log) == {}
