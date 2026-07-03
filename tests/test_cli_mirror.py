"""Tests for the `metatron mirror` CLI group (DB <-> markdown bundle)."""

import io

from metatron.cli import main
from metatron.models import Origin, Decision, Status
from metatron.storage.sqlite import SQLiteDecisionStore, SQLiteEventStore


def _candidate(pattern, scope="app") -> Decision:
    return Decision(
        repo="r",
        pattern=pattern,
        scope=scope,
        rationale="r",
        origin=Origin.BOOTSTRAP,
    )


def _run(argv, store):
    out = io.StringIO()
    code = main(argv, store=store, event_store=SQLiteEventStore(":memory:"), out=out)
    return code, out.getvalue()


def test_mirror_sync_writes_candidate_file(tmp_path):
    store = SQLiteDecisionStore(":memory:")
    store.add(_candidate("a candidate"))

    code, _ = _run(["mirror", "sync", "--repo", "r", "--root", str(tmp_path)], store)

    assert code == 0
    candidate_dir = tmp_path / "context" / "candidate"
    files = list(candidate_dir.glob("*.md"))
    assert files, "expected a candidate markdown file under metatron/candidate/"


def test_mirror_import_runs_clean_after_sync(tmp_path):
    store = SQLiteDecisionStore(":memory:")
    store.add(_candidate("a candidate"))

    sync_code, _ = _run(["mirror", "sync", "--repo", "r", "--root", str(tmp_path)], store)
    assert sync_code == 0

    code, output = _run(["mirror", "import", "--repo", "r", "--root", str(tmp_path)], store)

    assert code == 0
    assert "Imported:" in output


def test_mirror_import_promotes_when_file_moved_to_decisions(tmp_path):
    # Moving a candidate file into decisions/ is a human promotion; import applies it.
    store = SQLiteDecisionStore(":memory:")
    decision = _candidate("promote me")
    store.add(decision)

    _run(["mirror", "sync", "--repo", "r", "--root", str(tmp_path)], store)

    candidate_dir = tmp_path / "context" / "candidate"
    decisions_dir = tmp_path / "context" / "decisions"
    decisions_dir.mkdir(parents=True, exist_ok=True)
    md = next(candidate_dir.glob("*.md"))
    md.rename(decisions_dir / md.name)

    code, _ = _run(["mirror", "import", "--repo", "r", "--root", str(tmp_path)], store)

    assert code == 0
    assert store.get(decision.id).status is Status.CANONICAL
