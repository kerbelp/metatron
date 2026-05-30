"""Tests for deterministic signal aggregation over structure + history."""

from datetime import datetime, timezone

from metatron.extraction.signals import (
    RepoSignals,
    ScopeSignals,
    collect_signals,
    scope_of,
)
from metatron.gitlog.reader import Commit
from metatron.parsing.base import ClassDef, ParsedFile


def _commit(subject: str, files: list[str], body: str = "") -> Commit:
    return Commit(
        sha="0" * 40,
        author="Dev",
        date=datetime(2024, 1, 1, tzinfo=timezone.utc),
        subject=subject,
        body=body,
        files=files,
    )


def _scope(signals: RepoSignals, name: str) -> ScopeSignals:
    return next(s for s in signals.scopes if s.scope == name)


def test_scope_of_uses_parent_directory():
    assert scope_of("metatron/storage/sqlite.py") == "metatron/storage"


def test_scope_of_is_empty_for_top_level_files():
    assert scope_of("README.md") == ""


def test_counts_recurring_imports_per_scope():
    files = [
        ParsedFile(path="app/a.py", language="python", imports=["os", "typing"]),
        ParsedFile(path="app/b.py", language="python", imports=["os"]),
    ]
    signals = collect_signals(files, [])

    app = _scope(signals, "app")
    assert app.file_count == 2
    counts = {c.name: c.count for c in app.imports}
    assert counts == {"os": 2, "typing": 1}


def test_imports_sorted_by_count_then_name():
    files = [
        ParsedFile(path="app/a.py", language="python", imports=["b", "a", "a"]),
    ]
    app = _scope(collect_signals(files, []), "app")
    assert [(c.name, c.count) for c in app.imports] == [("a", 2), ("b", 1)]


def test_counts_class_base_classes():
    files = [
        ParsedFile(
            path="app/m.py",
            language="python",
            classes=[
                ClassDef(name="A", bases=["BaseModel"]),
                ClassDef(name="B", bases=["BaseModel"]),
            ],
        ),
    ]
    app = _scope(collect_signals(files, []), "app")
    assert {c.name: c.count for c in app.bases} == {"BaseModel": 2}


def test_history_attributes_churn_to_each_touched_scope():
    commits = [_commit("touch two areas", ["app/a.py", "lib/b.py"])]
    signals = collect_signals([], commits)

    assert _scope(signals, "app").commit_count == 1
    assert _scope(signals, "lib").commit_count == 1


def test_counts_fix_and_revert_commits_per_scope():
    commits = [
        _commit("fix: crash on empty input", ["app/a.py"]),
        _commit("Revert \"add caching\"", ["app/a.py"]),
        _commit("add feature", ["app/a.py"]),
    ]
    app = _scope(collect_signals([], commits), "app")
    assert app.commit_count == 3
    assert app.fix_count == 1
    assert app.revert_count == 1


def test_collects_commit_subjects_newest_first():
    # commits() returns newest-first; aggregation preserves that order.
    commits = [
        _commit("newer", ["app/a.py"]),
        _commit("older", ["app/a.py"]),
    ]
    app = _scope(collect_signals([], commits), "app")
    assert app.subjects == ["newer", "older"]


def test_scope_present_when_only_history_or_only_structure():
    files = [ParsedFile(path="app/a.py", language="python")]
    commits = [_commit("x", ["lib/b.py"])]
    signals = collect_signals(files, commits)
    assert {s.scope for s in signals.scopes} == {"app", "lib"}
