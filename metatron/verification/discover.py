"""Find verification contracts on disk and select them by scope / tags.

Selection mirrors decision serving (Paper 2: *selection beats volume*) — contracts
are scoped per subsystem and pulled on demand, never concatenated into one blob.
"""
from __future__ import annotations

from pathlib import Path

from metatron.config import resolve_context_dir
from metatron.verification.contract import VerificationContract, load_contract
from metatron.verification.schema import (
    OKF_TYPE,
    RESERVED_FILENAMES,
    VERIFICATION_DIR,
)


def verification_dir(root: str | Path = ".", context_dir: str | None = None) -> Path:
    """The canonical ``<context>/verification/`` directory for a repo."""
    return resolve_context_dir(root, context_dir) / VERIFICATION_DIR


def iter_contracts(base: Path) -> list[VerificationContract]:
    """Load every verification contract under ``base`` (typed, non-reserved)."""
    contracts: list[VerificationContract] = []
    base = Path(base)
    if not base.exists():
        return contracts
    for md in sorted(base.glob("*.md")):
        if md.name in RESERVED_FILENAMES:
            continue
        c = load_contract(md)
        if str(c.frontmatter.get("type") or "").strip() == OKF_TYPE:
            contracts.append(c)
    return contracts


def _parts(scope: str) -> list[str]:
    return [p for p in str(scope or "").strip().strip("/").split("/") if p]


def scope_matches(contract_scope: str, requested: str) -> bool:
    """True when a contract is relevant to a requested scope.

    Path-segment prefix either direction: a contract scoped to the requested
    subsystem, anything under it, or a broader contract that covers it.
    """
    if not requested:
        return True
    cs, rq = _parts(contract_scope), _parts(requested)
    if not cs:
        return False
    n = min(len(cs), len(rq))
    return cs[:n] == rq[:n]


def select(
    contracts: list[VerificationContract],
    *,
    scope: str | None = None,
    tags: list[str] | None = None,
) -> list[VerificationContract]:
    """Filter contracts by scope relevance and (if given) required tags.

    A contract passes the tag filter if any of its checks carries any requested
    tag; the runner further narrows to the matching checks.
    """
    out = contracts
    if scope:
        out = [c for c in out if scope_matches(c.scope, scope)]
    if tags:
        want = {t.strip().lower() for t in tags if t.strip()}
        out = [
            c for c in out
            if any(want & {t.lower() for t in chk.tags} for chk in c.checks)
        ]
    return out
