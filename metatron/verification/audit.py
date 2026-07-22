"""Read-only lint for verification contracts. Reports; changes nothing."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from metatron.verification.contract import load_contract
from metatron.verification.schema import OKF_TYPE, RESERVED_FILENAMES


@dataclass(frozen=True)
class AuditError:
    path: Path
    message: str


def audit_dir(base: Path, *, repo_root: Path | None = None) -> list[AuditError]:
    """Lint every contract under ``base``.

    Flags: wrong/missing OKF type, missing scope, dangling ``source_refs``,
    checks without an action or without assertions, and unparseable assertions.
    """
    base = Path(base)
    repo_root = Path(repo_root) if repo_root else base.parent.parent
    errors: list[AuditError] = []
    if not base.exists():
        return errors
    for md in sorted(base.glob("*.md")):
        if md.name in RESERVED_FILENAMES:
            continue
        c = load_contract(md)
        declared = str(c.frontmatter.get("type") or "").strip()
        if declared != OKF_TYPE:
            errors.append(AuditError(
                md, f"type must be {OKF_TYPE!r} (got {declared or 'none'})"))
        if not c.scope:
            errors.append(AuditError(md, "missing required field: scope"))
        for ref in c.frontmatter.get("source_refs") or []:
            if not (repo_root / str(ref)).exists():
                errors.append(AuditError(md, f"source_ref points at missing path: {ref}"))
        if not c.checks:
            errors.append(AuditError(md, "contract has no checks"))
        for chk in c.checks:
            if not chk.action.strip():
                errors.append(AuditError(md, f"check {chk.name!r} has no Action"))
            if not chk.expects:
                errors.append(AuditError(md, f"check {chk.name!r} has no Expect assertions"))
            for a in chk.expects:
                if a.kind == "invalid":
                    errors.append(AuditError(
                        md, f"check {chk.name!r}: unparseable assertion: {a.raw}"))
    return errors
