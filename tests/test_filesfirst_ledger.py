from datetime import datetime

from metatron.filesfirst.ledger import LedgerEntry, append_entries, read_entries, entries_from_commit


def _entry(decision_id, kind, day="2026-06-18", sha="abc123"):
    return LedgerEntry(date=day, sha=sha, decision_id=decision_id, kind=kind)


class _FakeCommit:
    def __init__(self, sha, date, body):
        self.sha = sha
        self.date = date
        self.body = body


def test_matched_entries_go_to_month_shard(tmp_path):
    log = tmp_path / "log"
    append_entries(log, [_entry("token-refresh", "applied")], known_ids={"token-refresh"})
    shard = log / "2026-06.md"
    assert shard.exists()
    assert "token-refresh" in shard.read_text()
    assert (log / "unmatched.md").exists() is False


def test_unmatched_ids_are_quarantined_not_counted(tmp_path):
    log = tmp_path / "log"
    append_entries(log, [_entry("typo-id", "applied")], known_ids={"real-id"})
    assert (log / "2026-06.md").exists() is False
    assert "typo-id" in (log / "unmatched.md").read_text()


def test_append_is_idempotent_on_sha_id_kind(tmp_path):
    log = tmp_path / "log"
    e = _entry("d", "applied")
    append_entries(log, [e], known_ids={"d"})
    append_entries(log, [e], known_ids={"d"})  # same sha+id+kind again
    rows = read_entries(log / "2026-06.md")
    assert len(rows) == 1


def test_read_round_trips_entries(tmp_path):
    log = tmp_path / "log"
    append_entries(log, [_entry("d", "violated", day="2026-06-30")], known_ids={"d"})
    rows = read_entries(log / "2026-06.md")
    assert rows[0].decision_id == "d"
    assert rows[0].kind == "violated"
    assert rows[0].date == "2026-06-30"


def test_entries_from_commit_expands_trailers():
    c = _FakeCommit(
        "deadbeef", datetime(2026, 6, 18, 9, 0),
        "msg\n\nDecisions-Applied: a, b\nDecisions-Violated: c\n")
    entries = entries_from_commit(c)
    kinds = {(e.decision_id, e.kind) for e in entries}
    assert kinds == {("a", "applied"), ("b", "applied"), ("c", "violated")}
    assert all(e.sha == "deadbeef" and e.date == "2026-06-18" for e in entries)
