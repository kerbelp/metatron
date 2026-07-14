"""Files-first backing for the curation UI (``metatron ui --files``).

In files-first mode the git-tracked OKF markdown bundle is the source of truth
and the UI's store is a throwaway index rebuilt from it (the same relationship
``metatron mirror import`` maintains for the CLI). This module owns that
relationship for the web UI:

- ``refresh()`` re-imports the bundle into the (in-memory) store, so the UI
  always renders what the files say.
- ``status()`` feeds the ``/api/mode`` endpoint: which root is mounted and how
  many knowledge-base files are currently modified in the git working tree —
  the UI shows this so the human knows there are edits awaiting an ordinary
  git review.

Curation actions are file operations on the git working tree: an edit
re-renders the concept file, promotion is a ``git mv`` across the status
directories, rejection is a ``git rm``, and a new decision is a new candidate
file. Nothing here ever commits — the human reviews and lands every change
through the repository's normal git flow, which is what keeps the canonical
boundary human-gated in this mode.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from metatron.config import resolve_context_dir
from metatron.filesfirst.schema import RESERVED_FILENAMES
from metatron.mirror.layout import slug_for, status_for_path
from metatron.mirror.render import parse_document, render_document
from metatron.mirror.sync_import import ImportResult, import_bundle
from metatron.models import Status

_STATUS_DIRS = {Status.CANONICAL: "decisions", Status.CANDIDATE: "candidate"}


class FilesMode:
    """One mounted files-first repo behind the UI's store."""

    def __init__(self, store, root: Path | str, repo: str | None = None,
                 context_dir: str | None = None):
        self.store = store
        self.root = Path(root).resolve()
        self.context_dir = context_dir
        # The repo id only namespaces the throwaway index; the directory name
        # is the human-recognizable choice.
        self.repo = repo or self.root.name
        # decision id -> concept file, rebuilt on every refresh. Files exported
        # by `mirror sync` carry their id in frontmatter; hand-authored files
        # may not, and are matched by (pattern, scope, status) instead.
        self.paths: dict[str, Path] = {}

    def kb_dir(self) -> Path:
        return resolve_context_dir(self.root, self.context_dir)

    def refresh(self) -> ImportResult:
        """Rebuild the store from the files. The files always win."""
        res = import_bundle(
            self.store, repo=self.repo, root=self.root, context_dir=self.context_dir
        )
        self._map_paths()
        return res

    def _map_paths(self) -> None:
        self.paths = {}
        kb = self.kb_dir()
        decisions = {d.id: d for d in self.store.list(repo=self.repo)}
        by_content: dict[tuple, list] = {}
        for d in decisions.values():
            key = (d.pattern.strip(), d.scope.strip(), d.status)
            by_content.setdefault(key, []).append(d)
        for status_dir in ("candidate", "decisions"):
            for path in sorted((kb / status_dir).glob("*.md")):
                if path.name in RESERVED_FILENAMES:
                    continue
                fields = parse_document(path.read_text())
                did = fields.get("id")
                if did and did in decisions:
                    self.paths[did] = path
                    continue
                key = ((fields.get("pattern") or "").strip(),
                       (fields.get("scope") or "").strip(),
                       status_for_path(path))
                unmatched = [d for d in by_content.get(key, [])
                             if d.id not in self.paths]
                if len(unmatched) == 1:
                    self.paths[unmatched[0].id] = path

    # --- write path: every mutation is a working-tree edit, never a commit ---

    def has_file(self, decision_id: str) -> bool:
        return decision_id in self.paths

    def write_back(self, decision_id: str) -> None:
        """Re-render an edited decision into its concept file (normalizes the
        document to the canonical mirror form, which also pins the id)."""
        d = self.store.get(decision_id)
        path = self.paths[decision_id]
        path.write_text(render_document(d, None))

    def write_new(self, decision_id: str) -> None:
        """Materialize a UI-created candidate as a new concept file."""
        d = self.store.get(decision_id)
        path = self.kb_dir() / "candidate" / slug_for(d)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_document(d, None))
        self.paths[decision_id] = path

    def move_to_status_dir(self, decision_id: str) -> None:
        """Move the concept file to the directory encoding its (new) status.

        A pure move (``git mv`` when possible) — the file content is untouched,
        so the review diff is exactly the promotion, nothing else.
        """
        d = self.store.get(decision_id)
        path = self.paths[decision_id]
        target = self.kb_dir() / _STATUS_DIRS[d.status] / path.name
        if target == path:
            return
        if not self._git("mv", str(path), str(target)):
            path.rename(target)
        self.paths[decision_id] = target

    def remove_file(self, decision_id: str) -> None:
        path = self.paths.pop(decision_id)
        if not self._git("rm", "-f", "-q", str(path)):
            path.unlink(missing_ok=True)

    def _git(self, *args: str) -> bool:
        try:
            out = subprocess.run(["git", "-C", str(self.root), *args],
                                 capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            return False
        return out.returncode == 0

    def activity(self, limit: int = 60) -> dict:
        """Knowledge activity reconstructed from the KB's git history.

        The files-mode counterpart of the MCP event stream: each commit that
        touched the status directories is an activity event, and a rename from
        ``candidate/`` to ``decisions/`` *is* a promotion — that is exactly what
        the promotion workflow produces (``-M`` asks git to detect renames).
        """
        import re
        kb = self.kb_dir()
        try:
            out = subprocess.run(
                ["git", "-C", str(self.root), "log", f"-n{limit}", "-M",
                 "--pretty=format:%H|%an|%aI|%s", "--name-status", "--",
                 str(kb / "candidate"), str(kb / "decisions")],
                capture_output=True, text=True, timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            out = None
        commits: list[dict] = []
        totals = {"proposed": 0, "promoted": 0, "edited": 0, "removed": 0}
        authors: set[str] = set()
        if out is not None and out.returncode == 0:
            header = re.compile(r"^[0-9a-f]{40}\|")
            cur = None
            for line in out.stdout.splitlines():
                if not line.strip():
                    continue
                if header.match(line):
                    sha, author, date, subject = line.split("|", 3)
                    cur = {"sha": sha[:9], "author": author, "date": date,
                           "subject": subject, "changes": []}
                    commits.append(cur)
                    authors.add(author)
                    continue
                if cur is None or "\t" not in line:
                    continue
                parts = line.split("\t")
                op, name = parts[0], Path(parts[-1]).name
                if name in RESERVED_FILENAMES or not name.endswith(".md"):
                    continue
                if op.startswith("R") and len(parts) == 3:
                    src, dst = Path(parts[1]).parent.name, Path(parts[2]).parent.name
                    kind = "promoted" if (src, dst) == ("candidate", "decisions") else "moved"
                elif op == "A":
                    kind = "adopted" if Path(parts[1]).parent.name == "decisions" else "proposed"
                elif op == "M":
                    kind = "edited"
                elif op == "D":
                    kind = "removed"
                else:
                    continue
                cur["changes"].append({"kind": kind, "file": name})
                if kind in ("proposed", "adopted"):
                    totals["proposed"] += 1
                elif kind in totals:
                    totals[kind] += 1
        decisions = self.store.list(repo=self.repo)
        return {
            "commits": commits,
            "summary": {
                **totals,
                "contributors": len(authors),
                "canonical": sum(1 for d in decisions if d.status is Status.CANONICAL),
                "candidate": sum(1 for d in decisions if d.status is Status.CANDIDATE),
                "dirty_files": len(self.dirty_files()),
            },
        }

    def dirty_files(self) -> list[str]:
        """Knowledge-base paths modified in the git working tree (porcelain lines).

        Empty outside a git repo or on any git error — the count is advisory
        UI copy, never a gate.
        """
        try:
            out = subprocess.run(
                ["git", "-C", str(self.root), "status", "--porcelain", "--untracked-files=all", "--",
                 str(self.kb_dir())],
                capture_output=True, text=True, timeout=5,
            )
        except (OSError, subprocess.SubprocessError):
            return []
        if out.returncode != 0:
            return []
        return [line for line in out.stdout.splitlines() if line.strip()]

    def status(self) -> dict:
        return {
            "mode": "files",
            "root": str(self.root),
            "repo": self.repo,
            "kb_dir": str(self.kb_dir()),
            "dirty_files": len(self.dirty_files()),
        }
