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

    code, output = _run(["candidates", "list", "--repo", "github.com/acme/app"], store)

    assert code == 0
    assert "a candidate" in output
    assert "a canonical" not in output


def test_candidates_list_filters_by_scope():
    store = SQLitePriorStore(":memory:")
    store.add(_candidate("app rule", scope="app"))
    store.add(_candidate("lib rule", scope="lib"))

    _, output = _run(
        ["candidates", "list", "--scope", "lib", "--repo", "github.com/acme/app"], store
    )

    assert "lib rule" in output
    assert "app rule" not in output


def test_candidates_list_is_exclusive_to_the_current_repo(monkeypatch):
    # Priors are scoped to a repo — listing never bleeds across repos.
    store = SQLitePriorStore(":memory:")
    store.add(_candidate("here rule"))  # repo github.com/acme/app
    store.add(
        Prior(repo="github.com/acme/other", pattern="other rule", scope="app",
              rationale="r", origin=Origin.BOOTSTRAP)
    )
    monkeypatch.setenv("METATRON_REPO", "github.com/acme/app")

    _, scoped = _run(["candidates", "list"], store)
    assert "here rule" in scoped
    assert "other rule" not in scoped


def test_repo_list_shows_repos_with_counts():
    store = SQLitePriorStore(":memory:")
    store.add(_candidate("a"))  # acme/app candidate
    canon = _candidate("b")
    store.add(canon)
    store.set_status(canon.id, Status.CANONICAL)  # acme/app canonical
    store.add(
        Prior(repo="github.com/acme/other", pattern="c", scope="app",
              rationale="r", origin=Origin.BOOTSTRAP)
    )

    code, output = _run(["repo", "list"], store)

    assert code == 0
    assert "github.com/acme/app" in output
    assert "github.com/acme/other" in output
    assert "canonical=1" in output
    assert "candidates=1" in output


def test_repo_list_empty_is_friendly():
    code, output = _run(["repo", "list"], SQLitePriorStore(":memory:"))
    assert code == 0
    assert "No repos" in output


def test_candidates_list_announces_resolved_repo(monkeypatch):
    # The resolved repo is echoed so the acted-on repo is never a mystery.
    store = SQLitePriorStore(":memory:")
    store.add(_candidate("here rule"))  # only repo: github.com/acme/app
    monkeypatch.delenv("METATRON_REPO", raising=False)
    monkeypatch.setattr("metatron.cli.repo_id", lambda _: "github.com/unrelated/cwd")

    code, output = _run(["candidates", "list"], store)

    assert code == 0
    assert "Repo: github.com/acme/app" in output
    assert "here rule" in output


def test_candidates_list_ambiguous_repo_exits_with_guidance(monkeypatch):
    store = SQLitePriorStore(":memory:")
    store.add(_candidate("a"))  # github.com/acme/app
    store.add(Prior(repo="github.com/acme/other", pattern="b", scope="app",
                    rationale="r", origin=Origin.BOOTSTRAP))
    monkeypatch.delenv("METATRON_REPO", raising=False)
    monkeypatch.setattr("metatron.cli.repo_id", lambda _: "github.com/unrelated/cwd")

    code, output = _run(["candidates", "list"], store)

    assert code == 2
    assert "github.com/acme/app" in output and "github.com/acme/other" in output
    assert "repo set" in output


def test_repo_set_persists_default_and_list_marks_it(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # so metatron.toml is written/read here, not the repo
    monkeypatch.delenv("METATRON_REPO", raising=False)
    monkeypatch.delenv("METATRON_DB", raising=False)
    store = SQLitePriorStore(":memory:")
    store.add(_candidate("x"))  # github.com/acme/app

    set_code, set_out = _run(["repo", "set", "github.com/acme/app"], store)
    assert set_code == 0
    assert "Default repo set to github.com/acme/app" in set_out

    _, list_out = _run(["repo", "list"], store)
    assert "github.com/acme/app" in list_out and "(default)" in list_out

    unset_code, unset_out = _run(["repo", "unset"], store)
    assert unset_code == 0 and "cleared" in unset_out
    _, list_out2 = _run(["repo", "list"], store)
    assert "(default)" not in list_out2


def test_resolve_repo_precedence(monkeypatch):
    from metatron.cli import _resolve_repo
    from metatron.config import Settings

    store = SQLitePriorStore(":memory:")
    store.add(_candidate("x"))  # repo github.com/acme/app
    settings = Settings(default_repo="github.com/persisted/repo")
    # cwd id is controlled so the "inside a tracked repo" branch is deterministic.
    monkeypatch.setattr("metatron.cli.repo_id", lambda _: "github.com/cwd/repo")

    monkeypatch.setenv("METATRON_REPO", "github.com/env/repo")
    # explicit beats env beats persisted default
    assert _resolve_repo("github.com/explicit/repo", store, settings) == "github.com/explicit/repo"
    assert _resolve_repo(None, store, settings) == "github.com/env/repo"

    monkeypatch.delenv("METATRON_REPO", raising=False)
    # persisted default beats cwd/store inference
    assert _resolve_repo(None, store, settings) == "github.com/persisted/repo"


def test_resolve_repo_uses_cwd_when_it_is_in_the_store(monkeypatch):
    from metatron.cli import _resolve_repo
    from metatron.config import Settings

    store = SQLitePriorStore(":memory:")
    store.add(_candidate("x"))  # github.com/acme/app
    store.add(Prior(repo="github.com/acme/other", pattern="y", scope="app",
                    rationale="r", origin=Origin.BOOTSTRAP))
    monkeypatch.delenv("METATRON_REPO", raising=False)
    monkeypatch.setattr("metatron.cli.repo_id", lambda _: "github.com/acme/other")
    # cwd matches a tracked repo, so it wins even though more than one repo exists
    assert _resolve_repo(None, store, Settings()) == "github.com/acme/other"


def test_resolve_repo_auto_picks_the_only_repo(monkeypatch):
    from metatron.cli import _resolve_repo
    from metatron.config import Settings

    store = SQLitePriorStore(":memory:")
    store.add(_candidate("x"))  # the only repo: github.com/acme/app
    monkeypatch.delenv("METATRON_REPO", raising=False)
    monkeypatch.setattr("metatron.cli.repo_id", lambda _: "github.com/unrelated/cwd")
    assert _resolve_repo(None, store, Settings()) == "github.com/acme/app"


def test_resolve_repo_falls_back_to_cwd_on_empty_store(monkeypatch):
    # A fresh image (e.g. Glama builds the container and runs `metatron serve`
    # before anything is ingested) has an empty store. Serving must still boot,
    # so resolution falls back to the cwd's identity rather than raising.
    from metatron.cli import _resolve_repo
    from metatron.config import Settings

    store = SQLitePriorStore(":memory:")  # empty: no repos
    monkeypatch.delenv("METATRON_REPO", raising=False)
    monkeypatch.setattr("metatron.cli.repo_id", lambda _: "github.com/fresh/clone")
    assert _resolve_repo(None, store, Settings()) == "github.com/fresh/clone"


def test_resolve_repo_ambiguous_raises_with_guidance(monkeypatch):
    import pytest

    from metatron.cli import RepoResolutionError, _resolve_repo
    from metatron.config import Settings

    store = SQLitePriorStore(":memory:")
    store.add(_candidate("x"))  # github.com/acme/app
    store.add(Prior(repo="github.com/acme/other", pattern="y", scope="app",
                    rationale="r", origin=Origin.BOOTSTRAP))
    monkeypatch.delenv("METATRON_REPO", raising=False)
    monkeypatch.setattr("metatron.cli.repo_id", lambda _: "github.com/unrelated/cwd")
    with pytest.raises(RepoResolutionError) as exc:
        _resolve_repo(None, store, Settings())
    msg = str(exc.value)
    assert "github.com/acme/app" in msg and "github.com/acme/other" in msg
    assert "repo set" in msg


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


class JudgeProvider(LLMProvider):
    def complete(self, prompt: str) -> str:
        import json
        import re

        ns = [int(n) for n in re.findall(r'"n":\s*(\d+)', prompt)]
        return json.dumps([{"n": n, "verdict": "approve", "reason": "ok"} for n in ns])


def test_triage_sets_advisory_verdicts_on_candidates():
    from metatron.models import TriageVerdict

    store = SQLitePriorStore(":memory:")
    a, b = _candidate("one"), _candidate("two")
    store.add(a)
    store.add(b)

    code = main(
        ["triage", "--repo", "github.com/acme/app"],
        store=store,
        provider=JudgeProvider(),
        out=io.StringIO(),
    )

    assert code == 0
    assert store.get(a.id).triage is TriageVerdict.APPROVE
    assert store.get(a.id).triage_reason == "ok"
    # triage does NOT change status — still a candidate
    assert store.get(a.id).status is Status.CANDIDATE


def test_triage_prints_live_progress():
    store = SQLitePriorStore(":memory:")
    for i in range(3):
        store.add(_candidate(f"cand {i}"))
    out = io.StringIO()

    main(["triage", "--repo", "github.com/acme/app"],
         store=store, provider=JudgeProvider(), out=out)

    output = out.getvalue()
    assert "Judging 3 candidate(s)" in output
    assert "[batch 1/1]" in output


class RefinerProvider(LLMProvider):
    model = "claude-opus-4-8"

    def complete(self, prompt: str) -> str:
        import json
        return json.dumps([
            {"pattern": "Mirror the order_created webhook publish chain",
             "scope": "src/api", "rationale": "consistency", "confidence": "high"},
        ])


def test_refine_feedback_creates_structured_candidates_and_marks_handled():
    from metatron.events import Event, EventKind
    from metatron.storage.sqlite import SQLiteEventStore

    store = SQLitePriorStore(":memory:")
    events = SQLiteEventStore(":memory:")
    events.record(Event(repo="github.com/acme/app", kind=EventKind.FEEDBACK,
                        missing="the credit path must mirror order_created", area="src/api"))

    code = main(
        ["refine-feedback", "--repo", "github.com/acme/app"],
        store=store,
        provider=RefinerProvider(),
        event_store=events,
        out=io.StringIO(),
    )

    assert code == 0
    cands = store.list(repo="github.com/acme/app")
    assert len(cands) == 1
    assert cands[0].origin is Origin.AGENT_FEEDBACK
    assert cands[0].status is Status.CANDIDATE
    assert events.unhandled_feedback(repo="github.com/acme/app") == []  # marked handled


def test_refine_feedback_prints_live_progress():
    # Each event is a slow LLM call; the CLI must show it's working, not look hung.
    from metatron.events import Event, EventKind
    from metatron.storage.sqlite import SQLiteEventStore

    store = SQLitePriorStore(":memory:")
    events = SQLiteEventStore(":memory:")
    for area in ("src/api", "src/db"):
        events.record(Event(repo="github.com/acme/app", kind=EventKind.FEEDBACK,
                            missing=f"gap in {area}", area=area))
    out = io.StringIO()

    main(["refine-feedback", "--repo", "github.com/acme/app"],
         store=store, provider=RefinerProvider(), event_store=events, out=out)

    output = out.getvalue()
    assert "Refining 2 unhandled feedback report(s)" in output
    assert "[1/2] src/api" in output
    assert "[2/2] src/db" in output


def test_ingest_prints_live_progress(git_repo):
    # Extraction is one LLM call per scope; the CLI must show it's working.
    git_repo.commit("init", {"app/a.py": "import os\n", "lib/b.py": "import sys\n"})
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
    output = out.getvalue()
    assert "Ingesting" in output and "extracting" in output
    assert "[1/" in output  # at least one per-scope progress line


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
