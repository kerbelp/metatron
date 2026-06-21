from pathlib import Path

from metatron.filesfirst.ledger import LedgerEntry, append_entries
from metatron.filesfirst.report import DecisionMeta, load_decisions, load_window_entries


def _decision(d: Path, slug: str, status="canonical", title="T"):
    (d / f"{slug}.md").write_text(
        f"---\nid: {slug}\ntype: decision\nstatus: {status}\ntitle: {title}\n---\nb\n",
        encoding="utf-8")


def test_load_window_entries_filters_by_date_and_skips_unmatched(tmp_path):
    log = tmp_path / "log"
    append_entries(log, [
        LedgerEntry("2026-05-31", "s0", "d", "applied"),   # before window
        LedgerEntry("2026-06-10", "s1", "d", "applied"),   # in
        LedgerEntry("2026-06-30", "s2", "d", "applied"),   # in
        LedgerEntry("2026-07-01", "s3", "d", "applied"),   # after window
    ], known_ids={"d"})
    append_entries(log, [LedgerEntry("2026-06-15", "s4", "ghost", "applied")],
                   known_ids={"real"})  # -> unmatched.md, must be ignored
    got = load_window_entries(log, "2026-06-01", "2026-06-30")
    shas = sorted(e.sha for e in got)
    assert shas == ["s1", "s2"]


def test_load_decisions_reads_id_title_status(tmp_path):
    _decision(tmp_path, "token-refresh", status="candidate", title="Refresh server-side")
    (tmp_path / "index.md").write_text("# generated\n", encoding="utf-8")
    metas = load_decisions(tmp_path)
    assert metas["token-refresh"] == DecisionMeta(
        id="token-refresh", title="Refresh server-side", status="candidate")
