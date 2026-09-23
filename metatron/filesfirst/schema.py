from __future__ import annotations

from uuid import UUID

# Decision lifecycle. Status lives in frontmatter, never in directory names.
STATUSES: tuple[str, ...] = ("candidate", "canonical", "superseded", "deprecated")

CONFIDENCE: tuple[str, ...] = ("low", "medium", "high")

# OKF requires `type` — and nothing else. An explicit `id` is an optional durable
# identity independent of the readable filename; without one, the filename slug
# is the identity. `status` defaults to the containing directory (candidate/ vs
# decisions/); `title` is optional.
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


def is_uuid_slug(value: str) -> bool:
    """Whether *value* is a bare canonical UUID rather than a readable slug."""
    try:
        return str(UUID(value)) == value.lower()
    except (ValueError, AttributeError):
        return False
