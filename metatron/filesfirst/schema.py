from __future__ import annotations

# Decision lifecycle. Status lives in frontmatter, never in directory names.
STATUSES: tuple[str, ...] = ("candidate", "canonical", "superseded", "deprecated")

CONFIDENCE: tuple[str, ...] = ("low", "medium", "high")

# OKF requires `type` — and nothing else. A file's identity is its filename slug;
# an explicit `id` is optional (it is minted at `mirror import` time when a repo
# migrates to the SQLite index) and must match the slug when present. `status`
# defaults to the containing directory (candidate/ vs decisions/); `title` is
# optional.
REQUIRED_FIELDS: tuple[str, ...] = ("type",)

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
