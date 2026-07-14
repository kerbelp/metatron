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

Nothing here ever commits: any future write path produces working-tree changes
for a human to review and land through the repository's normal git flow.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from metatron.config import resolve_context_dir
from metatron.mirror.sync_import import ImportResult, import_bundle


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

    def kb_dir(self) -> Path:
        return resolve_context_dir(self.root, self.context_dir)

    def refresh(self) -> ImportResult:
        """Rebuild the store from the files. The files always win."""
        return import_bundle(
            self.store, repo=self.repo, root=self.root, context_dir=self.context_dir
        )

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
