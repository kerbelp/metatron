"""Stable file identity and directory-as-status mapping for the mirror.

Filename = short prefix of the durable decision id + SHA-1 digest of that id,
so editing any mutable field (pattern, rationale, keywords, …) never orphans git
history.  The readable head is derived solely from ``Decision.id``, not from
``pattern`` or any other mutable field — this is the invariant that keeps
``git mv`` promotions clean.

The directory (``candidate/`` vs ``decisions/``) *is* the status; no separate
status column is stored in the filename or file body for path-routing purposes.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from metatron.config import DEFAULT_CONTEXT_DIR
from metatron.models import Decision, Status

_STATUS_DIR: dict[Status, str] = {
    Status.CANDIDATE: "candidate",
    Status.CANONICAL: "decisions",
}
_DIR_STATUS: dict[str, Status] = {v: k for k, v in _STATUS_DIR.items()}


def slug_for(d: Decision) -> str:
    """Return a stable filename slug derived exclusively from ``d.id``.

    The slug is ``<id-prefix>-<sha1-digest>.md`` where:
    - ``id-prefix`` is the first 8 characters of the UUID (before the first
      hyphen), giving a short human-readable token that never changes.
    - ``sha1-digest`` is the first 6 hex characters of the SHA-1 hash of the
      full id string, providing additional collision resistance.

    Because both components come from ``d.id`` — which is immutable after
    creation — the slug is stable across any content edits.
    """
    id_str = d.id
    prefix = id_str.split("-")[0]  # first 8 hex chars of the UUID
    digest = hashlib.sha1(id_str.encode("utf-8")).hexdigest()[:6]
    return f"decision-{prefix}-{digest}.md"


def path_for(d: Decision, root: Path | None = None) -> Path:
    """Return the canonical filesystem path for *d* under *root*.

    *root* is the knowledge-base directory itself (resolve it with
    :func:`metatron.config.resolve_context_dir`); the default is the bare
    ``context/`` name. The parent directory encodes the status (``candidate/``
    or ``decisions/``). Raises ``KeyError`` for statuses that are not mirrored
    (e.g. REJECTED).
    """
    root = Path(DEFAULT_CONTEXT_DIR) if root is None else root
    return root / _STATUS_DIR[d.status] / slug_for(d)


def status_for_path(path: Path) -> Status:
    """Infer the decision status from the parent directory name of *path*.

    Raises ``KeyError`` if the directory name is not a known status directory.
    """
    return _DIR_STATUS[Path(path).parent.name]
