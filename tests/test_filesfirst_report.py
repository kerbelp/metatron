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


from metatron.filesfirst.report import Report, build_report


def _metas(*rows):
    return {r[0]: DecisionMeta(id=r[0], title=r[1], status=r[2]) for r in rows}


def test_build_report_computes_all_metrics():
    entries = [
        LedgerEntry("2026-06-10", "s1", "token-refresh", "applied"),
        LedgerEntry("2026-06-11", "s2", "token-refresh", "applied"),
        LedgerEntry("2026-06-12", "s2", "auth-ttl", "applied"),       # same commit, 2nd decision
        LedgerEntry("2026-06-13", "s3", "legacy-retry", "violated"),
        LedgerEntry("2026-06-13", "s3", "token-refresh", "considered"),  # not counted as reuse
    ]
    decisions = _metas(
        ("token-refresh", "Refresh server-side", "canonical"),
        ("auth-ttl", "Session TTL", "canonical"),
        ("legacy-retry", "Old retry policy", "deprecated"),
        ("draft-thing", "A candidate", "candidate"),
    )
    r = build_report(entries, total_commits=5, decisions=decisions,
                     start="2026-06-08", end="2026-06-14")

    # adoption: commits s1,s2,s3 carried trailers => 3 of 5 = 60%
    assert r.consulted_commits == 3
    assert r.total_commits == 5
    assert r.adoption_pct == 60.0
    # reuse: token-refresh applied 2x, auth-ttl 1x (considered does not count)
    assert r.reuse[0] == ("token-refresh", "Refresh server-side", 2)
    assert ("auth-ttl", "Session TTL", 1) in r.reuse
    assert all(decision_id != "legacy-retry" for decision_id, _, _ in r.reuse)
    # drift: one violation, with its title resolved
    assert r.violations == [("legacy-retry", "Old retry policy", "s3")]
    # curation: status distribution + candidate backlog
    assert r.status_counts["canonical"] == 2
    assert r.status_counts["candidate"] == 1
    assert r.candidates_awaiting == 1


def test_build_report_handles_zero_commits():
    r = build_report([], total_commits=0, decisions={}, start="2026-06-01", end="2026-06-07")
    assert r.adoption_pct == 0.0
    assert r.reuse == [] and r.violations == []


from metatron.filesfirst.report import render_markdown


def test_render_markdown_is_deterministic_and_complete():
    r = Report(
        start="2026-06-08", end="2026-06-14",
        total_commits=5, consulted_commits=3, adoption_pct=60.0,
        reuse=[("token-refresh", "Refresh server-side", 2), ("auth-ttl", "Session TTL", 1)],
        violations=[("legacy-retry", "Old retry policy", "s3abc")],
        status_counts={"canonical": 2, "candidate": 1, "deprecated": 1},
        candidates_awaiting=1,
    )
    md = render_markdown(r)
    assert md == (
        "# Decision usage digest\n\n"
        "**Window:** 2026-06-08 to 2026-06-14\n\n"
        "## Adoption\n\n"
        "3 of 5 commits (60.0%) consulted a decision.\n\n"
        "## Knowledge reuse\n\n"
        "| decision | title | applied |\n|---|---|---|\n"
        "| `token-refresh` | Refresh server-side | 2 |\n"
        "| `auth-ttl` | Session TTL | 1 |\n\n"
        "## Drift caught\n\n"
        "| decision | title | commit |\n|---|---|---|\n"
        "| `legacy-retry` | Old retry policy | `s3abc` |\n\n"
        "## Curation health\n\n"
        "| status | count |\n|---|---|\n"
        "| candidate | 1 |\n| canonical | 2 |\n| deprecated | 1 |\n\n"
        "1 candidate(s) awaiting promotion.\n\n"
        "---\n\n"
        "_Every count above traces to a merged commit trailer._\n"
    )


def test_render_markdown_handles_empty_sections():
    r = Report("2026-06-01", "2026-06-07", 0, 0, 0.0, [], [], {}, 0)
    md = render_markdown(r)
    assert "0 of 0 commits (0.0%) consulted a decision." in md
    assert "_No decisions applied in this window._" in md
    assert "_No drift caught in this window._" in md
