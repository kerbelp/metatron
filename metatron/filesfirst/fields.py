"""Field ownership enforcement for decision frontmatter edits."""

from __future__ import annotations

from metatron.filesfirst.schema import HUMAN_FIELDS, MACHINE_FIELDS


def changed_fields(old: dict, new: dict) -> set[str]:
    """Field names whose value was added, removed, or modified between two
    frontmatter dicts."""
    return {k for k in old.keys() | new.keys() if old.get(k) != new.get(k)}


def ownership_violations(changed: set[str], *, actor: str) -> set[str]:
    """The subset of `changed` fields this actor is not allowed to edit.

    actor="human": machine-owned fields are off-limits.
    actor="ci":    human-owned fields are off-limits.
    Fields in neither ownership set are unconstrained.
    """
    forbidden = MACHINE_FIELDS if actor == "human" else HUMAN_FIELDS
    return changed & forbidden
