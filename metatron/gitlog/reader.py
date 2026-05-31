"""Read commit history (messages, authors, changed files) via the ``git`` CLI.

Commit messages and the files they touch are the raw material for history-based
signals: where churn concentrates, what the recurring "why" is, where fixes and
reverts cluster. Diffs are intentionally not read yet — subjects/bodies + changed
paths are the cheap, high-signal slice for the first milestone.
"""

from __future__ import annotations

import subprocess
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field

# Control characters as delimiters: commit messages won't contain these.
_RECORD = "\x1e"
_FIELD = "\x1f"
_FORMAT = _RECORD + _FIELD.join(["%H", "%an", "%aI", "%s", "%b"]) + _FIELD


class Commit(BaseModel):
    sha: str
    author: str
    date: datetime
    subject: str
    body: str = ""
    files: list[str] = Field(default_factory=list)


class GitLogReader:
    def __init__(self, repo_path: str | Path) -> None:
        self.repo_path = Path(repo_path)

    def commits(
        self,
        *,
        max_commits: int = 500,
        since: str | None = None,
        paths: list[str] | None = None,
    ) -> list[Commit]:
        """Return commits newest-first, capped at ``max_commits``.

        ``since`` is passed through to ``git log --since`` (e.g. ``"2024-01-01"``).
        ``paths`` restricts to commits touching those pathspecs, and limits each
        commit's listed files to the matching paths.
        """
        args = [
            "git",
            "-C",
            str(self.repo_path),
            "log",
            f"--max-count={max_commits}",
            "--name-only",
            f"--pretty=format:{_FORMAT}",
        ]
        if since is not None:
            args.append(f"--since={since}")
        if paths:
            args.extend(["--", *paths])

        result = subprocess.run(args, capture_output=True, text=True)
        if result.returncode != 0:
            # A repo with no commits yet has an unborn HEAD; that's empty, not an error.
            if "does not have any commits yet" in result.stderr:
                return []
            raise RuntimeError(f"git log failed: {result.stderr.strip()}")

        return [
            _parse_record(rec) for rec in result.stdout.split(_RECORD) if rec.strip()
        ]


def _parse_record(record: str) -> Commit:
    sha, author, date, subject, body, files_blob = record.split(_FIELD)[:6]
    files = [line for line in files_blob.splitlines() if line.strip()]
    return Commit(
        sha=sha,
        author=author,
        date=datetime.fromisoformat(date),
        subject=subject,
        body=body.strip(),
        files=files,
    )
