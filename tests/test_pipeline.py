"""Integration test for the end-to-end ingest pipeline."""

from metatron.extraction.provider import LLMProvider
from metatron.models import Origin, Status
from metatron.pipeline import ingest
from metatron.storage.sqlite import SQLitePriorStore

_RESPONSE = (
    '[{"pattern": "p", "scope": "app", "rationale": "r", "confidence": "high"}]'
)


class FakeProvider(LLMProvider):
    def __init__(self, response: str) -> None:
        self.response = response
        self.calls = 0

    def complete(self, prompt: str) -> str:
        self.calls += 1
        return self.response


def _populated_repo(git_repo):
    git_repo.commit(
        "init",
        {
            "app/models.py": "import os\nclass A(Base):\n    pass\n",
            "app/views.py": "import os\n",
            "README.md": "# hi\n",
        },
    )
    git_repo.commit("fix: a bug", {"app/models.py": "import os\n# fixed\n"})
    return git_repo


def test_ingest_parses_only_supported_files(git_repo):
    repo = _populated_repo(git_repo)
    result = ingest(repo.path, SQLitePriorStore(":memory:"), FakeProvider(_RESPONSE))
    # Two .py files; README.md has no parser and is skipped.
    assert result.files_parsed == 2


def test_ingest_reads_commits(git_repo):
    repo = _populated_repo(git_repo)
    result = ingest(repo.path, SQLitePriorStore(":memory:"), FakeProvider(_RESPONSE))
    assert result.commits_read == 2


def test_ingest_persists_extracted_priors(git_repo):
    repo = _populated_repo(git_repo)
    store = SQLitePriorStore(":memory:")
    result = ingest(repo.path, store, FakeProvider(_RESPONSE))

    stored = store.list()
    assert result.priors_created == len(stored) > 0


def test_ingested_priors_are_uncurated_bootstrap(git_repo):
    repo = _populated_repo(git_repo)
    store = SQLitePriorStore(":memory:")
    ingest(repo.path, store, FakeProvider(_RESPONSE))

    stored = store.list()
    assert stored
    assert all(p.status is Status.CANDIDATE for p in stored)
    assert all(p.origin is Origin.BOOTSTRAP for p in stored)


def test_ingest_path_prefix_scopes_parsing_and_history(git_repo):
    git_repo.commit(
        "init",
        {"app/a.py": "import os\n", "lib/b.py": "import sys\n"},
    )
    store = SQLitePriorStore(":memory:")

    result = ingest(
        git_repo.path,
        store,
        FakeProvider(_RESPONSE),
        path_prefix="app",
    )

    # Only the app/ file is parsed; lib/ is outside the scope.
    assert result.files_parsed == 1
    assert all(ref.ref.startswith("app") for p in store.list() for ref in p.source_refs)


def test_ingest_calls_provider_once_per_scope(git_repo):
    repo = _populated_repo(git_repo)
    provider = FakeProvider(_RESPONSE)
    result = ingest(repo.path, SQLitePriorStore(":memory:"), provider)
    assert provider.calls == result.scopes
