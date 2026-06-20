from __future__ import annotations

# Decision lifecycle. Status lives in frontmatter, never in directory names.
STATUSES: tuple[str, ...] = ("candidate", "canonical", "superseded", "deprecated")

CONFIDENCE: tuple[str, ...] = ("low", "medium", "high")

# OKF requires `type`; a files-first decision also requires these.
REQUIRED_FIELDS: tuple[str, ...] = ("id", "type", "status", "title")

# Authored and curated by humans / the proposing model.
HUMAN_FIELDS = frozenset(
    {"id", "type", "status", "title", "confidence", "keywords", "supersedes"}
)
# Derived from the usage ledger by CI; never hand-edited (enforced in a later plan).
MACHINE_FIELDS = frozenset(
    {"references", "violations", "created", "promoted", "last_applied"}
)

# Reserved OKF filenames that are not decisions.
RESERVED_FILENAMES = frozenset({"index.md", "log.md"})
