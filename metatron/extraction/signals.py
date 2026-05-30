"""Aggregate structural facts and git history into per-scope signal bundles.

This is the deterministic, no-LLM half of extraction. It turns raw parsed files
and commits into compact per-scope summaries (recurring imports/decorators/bases,
churn, fix/revert counts, the commit subjects that explain *why*). The LLM
extraction step consumes these bundles; keeping this layer pure (inputs in,
signals out) makes both halves independently testable.
"""

from __future__ import annotations

import re
from collections import Counter
from posixpath import dirname

from pydantic import BaseModel, Field

from metatron.gitlog.reader import Commit
from metatron.parsing.base import ParsedFile

_FIX_RE = re.compile(r"\b(fix|fixes|fixed|bug|bugfix|hotfix)\b", re.IGNORECASE)
_REVERT_RE = re.compile(r"\brevert", re.IGNORECASE)


class Counted(BaseModel):
    name: str
    count: int


class ScopeSignals(BaseModel):
    scope: str
    file_count: int = 0
    imports: list[Counted] = Field(default_factory=list)
    decorators: list[Counted] = Field(default_factory=list)
    bases: list[Counted] = Field(default_factory=list)
    commit_count: int = 0
    fix_count: int = 0
    revert_count: int = 0
    subjects: list[str] = Field(default_factory=list)


class RepoSignals(BaseModel):
    scopes: list[ScopeSignals] = Field(default_factory=list)


def scope_of(path: str) -> str:
    """The scope a file belongs to: its parent directory (``""`` at the root)."""
    return dirname(path)


def _ranked(counter: Counter) -> list[Counted]:
    ordered = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
    return [Counted(name=name, count=count) for name, count in ordered]


def collect_signals(
    parsed_files: list[ParsedFile],
    commits: list[Commit],
) -> RepoSignals:
    """Aggregate parsed files and commits (newest-first) into per-scope signals."""
    scopes: dict[str, _Accumulator] = {}

    def acc(scope: str) -> _Accumulator:
        return scopes.setdefault(scope, _Accumulator())

    for pf in parsed_files:
        a = acc(scope_of(pf.path))
        a.file_count += 1
        a.imports.update(pf.imports)
        a.decorators.update(pf.decorators)
        for cls in pf.classes:
            a.bases.update(cls.bases)

    for commit in commits:
        for scope in {scope_of(f) for f in commit.files}:
            a = acc(scope)
            a.commit_count += 1
            a.subjects.append(commit.subject)
            if _FIX_RE.search(commit.subject):
                a.fix_count += 1
            if _REVERT_RE.search(commit.subject):
                a.revert_count += 1

    return RepoSignals(
        scopes=[
            ScopeSignals(
                scope=name,
                file_count=a.file_count,
                imports=_ranked(a.imports),
                decorators=_ranked(a.decorators),
                bases=_ranked(a.bases),
                commit_count=a.commit_count,
                fix_count=a.fix_count,
                revert_count=a.revert_count,
                subjects=a.subjects,
            )
            for name, a in sorted(scopes.items())
        ]
    )


class _Accumulator:
    def __init__(self) -> None:
        self.file_count = 0
        self.imports: Counter = Counter()
        self.decorators: Counter = Counter()
        self.bases: Counter = Counter()
        self.commit_count = 0
        self.fix_count = 0
        self.revert_count = 0
        self.subjects: list[str] = []
