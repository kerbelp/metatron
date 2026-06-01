"""Tests for the curation CLI dispatch (store/provider injected, no processes)."""

import io
import os

from metatron.cli import main
from metatron.extraction.provider import LLMProvider
from metatron.models import Origin, Prior, Status
from metatron.storage.sqlite import SQLiteIngestRunStore, SQLitePriorStore


class FakeProvider(LLMProvider):
    def complete(self, prompt: str) -> str:
        return '[{"pattern": "p", "scope": "app", "rationale": "r", "confidence": "low"}]'


def _run(argv, store):
    out = io.StringIO()
    code = main(argv, store=store, out=out)
    return code, out.getvalue()


def _candidate(pattern, scope="app") -> Prior:
    return Prior(
        repo="github.com/acme/app",
        pattern=pattern,
        scope=scope,
        rationale="r",
        origin=Origin.BOOTSTRAP,
    )


def test_candidates_list_shows_candidates_only():
    store = SQLitePriorStore(":memory:")
    store.add(_candidate("a candidate"))
    canon = _candidate("a canonical")
    store.add(canon)
    store.set_status(canon.id, Status.CANONICAL)

    code, output = _run(["candidates", "list"], store)

    assert code == 0
    assert "a candidate" in output
    assert "a canonical" not in output


def test_candidates_list_filters_by_scope():
    store = SQLitePriorStore(":memory:")
    store.add(_candidate("app rule", scope="app"))
    store.add(_candidate("lib rule", scope="lib"))

    _, output = _run(["candidates", "list", "--scope", "lib"], store)

    assert "lib rule" in output
    assert "app rule" not in output


def test_candidates_approve_promotes_to_canonical():
    store = SQLitePriorStore(":memory:")
    prior = _candidate("promote me")
    store.add(prior)

    code, _ = _run(["candidates", "approve", prior.id], store)

    assert code == 0
    assert store.get(prior.id).status is Status.CANONICAL


def test_candidates_reject_marks_rejected():
    store = SQLitePriorStore(":memory:")
    prior = _candidate("reject me")
    store.add(prior)

    code, _ = _run(["candidates", "reject", prior.id], store)

    assert code == 0
    assert store.get(prior.id).status is Status.REJECTED


def test_approve_unknown_id_errors_without_raising():
    store = SQLitePriorStore(":memory:")
    code, output = _run(["candidates", "approve", "nope"], store)

    assert code != 0
    assert "nope" in output or "not found" in output.lower()


def test_cli_auto_loads_env_file_from_working_dir(tmp_path, monkeypatch):
    # Key sits in a .env in the working dir, not exported. The CLI should load it.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("ANTHROPIC_API_KEY=from-dotenv\n")

    main(["candidates", "list"], store=SQLitePriorStore(":memory:"), out=io.StringIO())

    assert os.environ["ANTHROPIC_API_KEY"] == "from-dotenv"


def test_cli_does_not_override_already_exported_env(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "from-shell")
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("ANTHROPIC_API_KEY=from-dotenv\n")

    main(["candidates", "list"], store=SQLitePriorStore(":memory:"), out=io.StringIO())

    assert os.environ["ANTHROPIC_API_KEY"] == "from-shell"


def test_ingest_path_option_scopes_to_subtree(git_repo):
    git_repo.commit("init", {"app/a.py": "import os\n", "lib/b.py": "import sys\n"})
    store = SQLitePriorStore(":memory:")

    code = main(
        ["ingest", str(git_repo.path), "--path", "app"],
        store=store,
        provider=FakeProvider(),
        run_store=SQLiteIngestRunStore(":memory:"),
        out=io.StringIO(),
    )

    assert code == 0
    assert store.list()
    assert all(
        ref.ref.startswith("app") for p in store.list() for ref in p.source_refs
    )


def test_ingest_stores_candidates_and_reports_summary(git_repo):
    git_repo.commit("init", {"app/a.py": "import os\n"})
    store = SQLitePriorStore(":memory:")

    out = io.StringIO()
    code = main(
        ["ingest", str(git_repo.path)],
        store=store,
        provider=FakeProvider(),
        run_store=SQLiteIngestRunStore(":memory:"),
        out=out,
    )

    assert code == 0
    assert store.list()  # priors were persisted
    assert all(p.status is Status.CANDIDATE for p in store.list())
