"""Open Knowledge Format (OKF) v0.1 view over the markdown decision mirror.

The exported bundle is already a valid OKF bundle: each decision is a concept
markdown file whose frontmatter carries the one required field, ``type``. This
module adds the OKF-flavoured extras on top of the plain export:

- ``export_okf_bundle`` writes the bundle, then an optional OKF directory listing
  (the bundle root (``index.md``)) enumerating every concept by its concept id.
- ``validate_okf_bundle`` checks the structural invariant that matters for OKF
  validity: every concept doc declares a non-empty ``type``.

Reserved filenames (``index.md``, ``log.md``) are listings/history, not concepts,
so they are exempt from the ``type`` requirement.
"""
from __future__ import annotations

from pathlib import Path

from metatron.config import resolve_context_dir
from metatron.mirror.export import export_bundle
from metatron.mirror.render import split_frontmatter

_RESERVED = frozenset({"index.md", "log.md"})


def _frontmatter(text: str) -> dict:
    """Parse the YAML frontmatter block of a markdown file, or {} if absent."""
    if not text.startswith("---"):
        return {}
    fm, _ = split_frontmatter(text)
    return fm


def _concept_id(bundle_root: Path, md_path: Path) -> str:
    """OKF concept id = path within the bundle, minus the ``.md`` suffix."""
    return md_path.relative_to(bundle_root).with_suffix("").as_posix()


def export_okf_bundle(store, repo: str, root: Path, events: list,
                      context_dir: str | None = None) -> dict[str, str]:
    """Export an OKF v0.1 bundle and an optional concept index.

    Delegates to ``export_bundle`` (which writes OKF-valid concept docs), then
    writes the bundle root (``index.md``) listing each concept by its concept id.
    """
    state = export_bundle(store, repo=repo, root=root, events=events,
                          context_dir=context_dir)
    bundle_root = resolve_context_dir(root, context_dir)
    concepts = sorted(
        p
        for p in bundle_root.rglob("*.md")
        if p.name not in _RESERVED
    )
    lines = ["# Metatron Decisions (OKF bundle)", ""]
    for p in concepts:
        cid = _concept_id(bundle_root, p)
        rel = p.relative_to(bundle_root).as_posix()
        lines.append(f"- [{cid}]({rel})")
    (bundle_root / "index.md").write_text("\n".join(lines) + "\n")
    return state


def validate_okf_bundle(root: Path, context_dir: str | None = None) -> list[str]:
    """Return structural OKF errors (empty list = valid bundle).

    Walks every concept ``.md`` file under the bundle root (excluding the
    reserved ``index.md``/``log.md``) and reports any that lack a non-empty
    ``type`` frontmatter field.
    """
    bundle_root = resolve_context_dir(root, context_dir)
    errors: list[str] = []
    for p in sorted(bundle_root.rglob("*.md")):
        if p.name in _RESERVED:
            continue
        fm = _frontmatter(p.read_text())
        if not str(fm.get("type") or "").strip():
            errors.append(
                f"{p.relative_to(bundle_root).as_posix()}: missing required "
                "OKF concept field 'type'"
            )
    return errors
