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


def test_posts_are_rejected_in_files_mode(served_files):
    fm, url = served_files
    decisions = fm.store.list(repo=fm.repo)
    req = urllib.request.Request(
        f"{url}/api/decisions/{decisions[0].id}/approve", method="POST")
    with pytest.raises(urllib.error.HTTPError) as err:
        urllib.request.urlopen(req)
    assert err.value.code == 409
    body = json.loads(err.value.read())
    assert "read-only" in body["error"]
    # And the store was not mutated behind the files' back.
    assert {d.status for d in fm.store.list(repo=fm.repo)} == \
        {Status.CANONICAL, Status.CANDIDATE}


def test_decisions_listing_serves_imported_files(served_files):
    fm, url = served_files
    with urllib.request.urlopen(url + f"/api/decisions?repo={fm.repo}") as r:
        body = json.loads(r.read())
    patterns = {d["pattern"] for d in body["items"]}
    assert patterns == {"Always use X.", "Consider Z."}
