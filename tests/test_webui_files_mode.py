"""Tests for the files-first curation UI mode (`metatron ui --files`)."""

import json
import subprocess
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from metatron.models import Status
from metatron.storage.sqlite import SQLiteDecisionStore, SQLiteEventStore
from metatron.webui.files_mode import FilesMode
from metatron.webui.server import find_free_port, make_server

_DOC = """\
---
type: Metatron Decision
scope: app/api
confidence: high
---

## Pattern
{pattern}

## Rationale
Because the offline repair path depends on it.
"""


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _bundle(tmp_path) -> Path:
    repo = tmp_path / "repo"
    (repo / "context" / "decisions").mkdir(parents=True)
    (repo / "context" / "candidate").mkdir(parents=True)
    (repo / "context" / "decisions" / "use-x.md").write_text(
        _DOC.format(pattern="Always use X."))
    (repo / "context" / "candidate" / "try-z.md").write_text(
        _DOC.format(pattern="Consider Z."))
    _git(repo, "init")
    _git(repo, "config", "user.email", "t@t.t")
    _git(repo, "config", "user.name", "t")
    return repo


def test_refresh_imports_files_at_directory_status(tmp_path):
    repo = _bundle(tmp_path)
    store = SQLiteDecisionStore(":memory:")
    fm = FilesMode(store, repo)
    fm.refresh()
    decisions = store.list(repo=fm.repo)
    assert {d.status for d in decisions} == {Status.CANONICAL, Status.CANDIDATE}
    assert {d.pattern for d in decisions} == {"Always use X.", "Consider Z."}


def test_dirty_files_tracks_uncommitted_kb_changes(tmp_path):
    repo = _bundle(tmp_path)
    fm = FilesMode(SQLiteDecisionStore(":memory:"), repo)
    assert len(fm.dirty_files()) == 2          # untracked bundle files
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "init")
    assert fm.dirty_files() == []
    (repo / "context" / "decisions" / "use-x.md").write_text(
        _DOC.format(pattern="Always use X, even on Sundays."))
    assert len(fm.dirty_files()) == 1


@pytest.fixture
def served_files(tmp_path):
    repo = _bundle(tmp_path)
    store = SQLiteDecisionStore(":memory:")
    fm = FilesMode(store, repo)
    fm.refresh()
    port = find_free_port(start=8850, host="127.0.0.1")
    httpd = make_server(store, "127.0.0.1", port, SQLiteEventStore(":memory:"),
                        files_mode=fm)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield fm, f"http://127.0.0.1:{port}"
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_mode_endpoint_reports_files(served_files):
    fm, url = served_files
    with urllib.request.urlopen(url + "/api/mode") as r:
        body = json.loads(r.read())
    assert body["mode"] == "files"
    assert body["kb_dir"].endswith("context")
    assert body["dirty_files"] == 2


def test_mode_endpoint_reports_db_without_files_mode():
    store = SQLiteDecisionStore(":memory:")
    port = find_free_port(start=8860, host="127.0.0.1")
    httpd = make_server(store, "127.0.0.1", port, SQLiteEventStore(":memory:"))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/mode") as r:
            assert json.loads(r.read()) == {"mode": "db"}
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_unmapped_decision_actions_return_404(served_files):
    fm, url = served_files
    req = urllib.request.Request(
        f"{url}/api/decisions/no-such-id/approve", method="POST")
    with pytest.raises(urllib.error.HTTPError) as err:
        urllib.request.urlopen(req)
    assert err.value.code == 404


def test_decisions_listing_serves_imported_files(served_files):
    fm, url = served_files
    with urllib.request.urlopen(url + f"/api/decisions?repo={fm.repo}") as r:
        body = json.loads(r.read())
    patterns = {d["pattern"] for d in body["items"]}
    assert patterns == {"Always use X.", "Consider Z."}


# --- phase 2: curation actions as working-tree edits ------------------------


def _post_json(url, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as r:
        return r.status, json.loads(r.read())


def test_approve_moves_file_between_status_dirs(served_files):
    fm, url = served_files
    cand = [d for d in fm.store.list(repo=fm.repo) if d.status is Status.CANDIDATE][0]
    old_path = fm.paths[cand.id]
    status, body = _post_json(f"{url}/api/decisions/{cand.id}/approve")
    assert status == 200 and body["ok"]
    new_path = fm.paths[cand.id]
    assert not old_path.exists()
    assert new_path.parent.name == "decisions" and new_path.exists()
    assert new_path.name == old_path.name              # pure move, no rename
    assert "Consider Z." in new_path.read_text()       # content untouched
    assert fm.store.get(cand.id).status is Status.CANONICAL


def test_update_rewrites_the_concept_file(served_files):
    fm, url = served_files
    d = [x for x in fm.store.list(repo=fm.repo) if x.status is Status.CANONICAL][0]
    status, body = _post_json(f"{url}/api/decisions/{d.id}/update",
                              {"pattern": "Always use X. Always."})
    assert status == 200 and body["ok"]
    text = fm.paths[d.id].read_text()
    assert "Always use X. Always." in text
    assert f"id: {d.id}" in text                       # normalization pins the id


def test_reject_removes_the_file(served_files):
    fm, url = served_files
    cand = [d for d in fm.store.list(repo=fm.repo) if d.status is Status.CANDIDATE][0]
    path = fm.paths[cand.id]
    status, body = _post_json(f"{url}/api/decisions/{cand.id}/reject")
    assert status == 200 and body["ok"]
    assert not path.exists()
    assert cand.id not in fm.paths


def test_create_writes_a_new_candidate_file(served_files):
    fm, url = served_files
    status, body = _post_json(f"{url}/api/decisions", {
        "pattern": "New rule.", "scope": "app", "rationale": "Because.",
    })
    assert status == 200 and body["ok"]
    path = fm.paths[body["id"]]
    assert path.parent.name == "candidate" and path.exists()
    assert "New rule." in path.read_text()


def test_llm_jobs_stay_unavailable_in_files_mode(served_files):
    fm, url = served_files
    req = urllib.request.Request(f"{url}/api/valuate/start", data=b"{}",
                                 method="POST",
                                 headers={"Content-Type": "application/json"})
    with pytest.raises(urllib.error.HTTPError) as err:
        urllib.request.urlopen(req)
    assert err.value.code == 409


def test_nothing_is_ever_committed(served_files):
    fm, url = served_files
    repo = fm.root
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "baseline")
    cand = [d for d in fm.store.list(repo=fm.repo) if d.status is Status.CANDIDATE][0]
    _post_json(f"{url}/api/decisions/{cand.id}/approve")
    log = subprocess.run(["git", "-C", str(repo), "log", "--oneline"],
                         capture_output=True, text=True).stdout
    assert len(log.strip().splitlines()) == 1          # still only the baseline
    assert len(fm.dirty_files()) > 0                   # the move awaits review


# --- git-history activity view ----------------------------------------------


def test_activity_classifies_history_and_counts(served_files):
    fm, url = served_files
    repo = fm.root
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "seed knowledge base")
    _git(repo, "mv", "context/candidate/try-z.md", "context/decisions/try-z.md")
    _git(repo, "commit", "-m", "Promote try-z after review")
    with urllib.request.urlopen(url + "/api/files-activity") as r:
        body = json.loads(r.read())
    kinds = [ch["kind"] for c in body["commits"] for ch in c["changes"]]
    assert "promoted" in kinds and "proposed" in kinds
    assert body["commits"][0]["subject"] == "Promote try-z after review"
    s = body["summary"]
    assert s["promoted"] == 1
    assert s["contributors"] == 1
    assert s["canonical"] + s["candidate"] == 2


def test_activity_endpoint_404_in_db_mode():
    store = SQLiteDecisionStore(":memory:")
    port = find_free_port(start=8870, host="127.0.0.1")
    httpd = make_server(store, "127.0.0.1", port, SQLiteEventStore(":memory:"))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        with pytest.raises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/files-activity")
        assert err.value.code == 404
    finally:
        httpd.shutdown()
        httpd.server_close()
