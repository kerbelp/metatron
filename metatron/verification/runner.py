"""Execute verification contracts — operator/CI only.

This is the ONLY code path in Metatron that runs a contract, and it is reached
only from ``metatron verification run`` (a foreground CLI the operator invokes in
their own shell) — never from the MCP/serving path, never agent-triggered. See
``docs/designs/2026-07-21-repository-verification-layer.md`` §6.
"""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from metatron.verification.contract import Assertion, Check, VerificationContract

# An optional LLM judge for `--judge` (phase 2): (invariant, contract) -> (ok, note).
Judge = Callable[[str, VerificationContract], "tuple[bool, str]"]

DEFAULT_TIMEOUT = 120


@dataclass
class AssertionResult:
    assertion: Assertion
    passed: bool
    detail: str = ""


@dataclass
class CheckResult:
    name: str
    passed: bool
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    assertions: list[AssertionResult] = field(default_factory=list)
    skipped: bool = False
    error: str = ""


@dataclass
class JudgedResult:
    invariant: str
    passed: bool
    note: str = ""


@dataclass
class ContractResult:
    slug: str
    scope: str
    setup_ok: bool = True
    setup_error: str = ""
    checks: list[CheckResult] = field(default_factory=list)
    judged: list[JudgedResult] = field(default_factory=list)
    teardown_ok: bool = True
    failure_means: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return (
            self.setup_ok
            and all(c.passed for c in self.checks if not c.skipped)
            and all(j.passed for j in self.judged)
        )


@dataclass
class RunReport:
    contracts: list[ContractResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.contracts)

    @property
    def total_checks(self) -> int:
        return sum(len(c.checks) for c in self.contracts)

    @property
    def failed_checks(self) -> int:
        return sum(
            1 for c in self.contracts for chk in c.checks
            if not chk.passed and not chk.skipped
        )


def _run_script(script: str, cwd: Path, timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", "-c", script],
        cwd=str(cwd), capture_output=True, text=True, timeout=timeout,
    )


def _resolve_jsonpath(data, path: str):
    """Resolve a minimal JSONPath (``$.a.b[0].c``). Returns a sentinel on miss."""
    if not path.startswith("$"):
        return _MISS
    cur = data
    for token in re.findall(r"\.([A-Za-z_][\w-]*)|\[(\d+)\]", path):
        key, idx = token
        try:
            if key:
                cur = cur[key]
            else:
                cur = cur[int(idx)]
        except (KeyError, IndexError, TypeError):
            return _MISS
    return cur


_MISS = object()


def _eval_assertion(a: Assertion, proc: subprocess.CompletedProcess,
                    cwd: Path, timeout: int) -> AssertionResult:
    if a.kind == "invalid":
        return AssertionResult(a, False, "unparseable assertion")
    if a.kind == "exit":
        ok = proc.returncode == a.code
        return AssertionResult(a, ok, f"exit was {proc.returncode}")
    if a.kind in ("contains", "matches"):
        stream = proc.stdout if a.stream == "stdout" else proc.stderr
        if a.kind == "contains":
            ok = a.text in stream
        else:
            ok = re.search(a.text, stream) is not None
        return AssertionResult(a, ok, "" if ok else f"not found in {a.stream}")
    if a.kind == "jsonpath":
        try:
            data = json.loads(proc.stdout)
        except (json.JSONDecodeError, ValueError):
            return AssertionResult(a, False, "stdout is not JSON")
        resolved = _resolve_jsonpath(data, a.path)
        if a.op == "exists":
            ok = resolved is not _MISS
            return AssertionResult(a, ok, "" if ok else "path missing")
        if resolved is _MISS:
            return AssertionResult(a, False, "path missing")
        try:
            expected = json.loads(a.value)
        except (json.JSONDecodeError, ValueError):
            expected = a.value
        ok = resolved == expected or str(resolved) == str(a.value)
        return AssertionResult(a, ok, "" if ok else f"got {resolved!r}")
    if a.kind == "shell":
        try:
            r = _run_script(a.text, cwd, timeout)
        except subprocess.TimeoutExpired:
            return AssertionResult(a, False, "shell assertion timed out")
        ok = r.returncode == 0
        return AssertionResult(a, ok, "" if ok else f"exit {r.returncode}")
    return AssertionResult(a, False, f"unknown kind {a.kind}")


def _run_check(check: Check, cwd: Path, timeout: int) -> CheckResult:
    if not check.action.strip():
        return CheckResult(check.name, passed=False, error="check has no Action")
    try:
        proc = _run_script(check.action, cwd, timeout)
    except subprocess.TimeoutExpired:
        return CheckResult(check.name, passed=False, error="action timed out")
    results = [_eval_assertion(a, proc, cwd, timeout) for a in check.expects]
    passed = bool(check.expects) and all(r.passed for r in results)
    return CheckResult(
        name=check.name, passed=passed, exit_code=proc.returncode,
        stdout=proc.stdout, stderr=proc.stderr, assertions=results,
        error="" if check.expects else "check has no assertions",
    )


def run_contract(
    contract: VerificationContract,
    *,
    cwd: str | Path = ".",
    tags: list[str] | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    judge: Judge | None = None,
) -> ContractResult:
    """Run one contract: setup -> checks -> (judged) -> teardown (always)."""
    cwd = Path(cwd)
    want = {t.strip().lower() for t in (tags or []) if t.strip()}
    res = ContractResult(
        slug=contract.slug, scope=contract.scope,
        failure_means=contract.failure_means,
    )

    if contract.setup.strip():
        try:
            sp = _run_script(contract.setup, cwd, timeout)
            if sp.returncode != 0:
                res.setup_ok = False
                res.setup_error = (sp.stderr or sp.stdout).strip()[:2000]
        except subprocess.TimeoutExpired:
            res.setup_ok, res.setup_error = False, "setup timed out"

    if res.setup_ok:
        for check in contract.checks:
            if want and not (want & {t.lower() for t in check.tags}):
                res.checks.append(CheckResult(check.name, passed=True, skipped=True))
                continue
            res.checks.append(_run_check(check, cwd, timeout))

        if judge is not None:
            for inv in contract.judged:
                try:
                    ok, note = judge(inv, contract)
                except Exception as exc:  # noqa: BLE001 - a judge fault fails the invariant, not the run
                    ok, note = False, f"judge error: {exc}"
                res.judged.append(JudgedResult(inv, ok, note))

    if contract.teardown.strip():
        try:
            tp = _run_script(contract.teardown, cwd, timeout)
            res.teardown_ok = tp.returncode == 0
        except subprocess.TimeoutExpired:
            res.teardown_ok = False

    return res


def run_contracts(
    contracts: list[VerificationContract],
    *,
    cwd: str | Path = ".",
    tags: list[str] | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    judge: Judge | None = None,
) -> RunReport:
    return RunReport(contracts=[
        run_contract(c, cwd=cwd, tags=tags, timeout=timeout, judge=judge)
        for c in contracts
    ])


def plan(contracts: list[VerificationContract], *, tags: list[str] | None = None) -> str:
    """Human-readable execution plan for ``--dry-run`` — resolves ordering and
    assertions, executes nothing (safe against an untrusted contract)."""
    want = {t.strip().lower() for t in (tags or []) if t.strip()}
    lines: list[str] = []
    for c in contracts:
        lines.append(f"contract: {c.slug}  (scope: {c.scope or '-'})")
        if c.setup.strip():
            lines.append("  setup:")
            lines += [f"    $ {ln}" for ln in c.setup.splitlines() if ln.strip()]
        for chk in c.checks:
            skip = " [SKIP: tag filter]" if want and not (
                want & {t.lower() for t in chk.tags}) else ""
            tagstr = f"  [tags: {', '.join(chk.tags)}]" if chk.tags else ""
            lines.append(f"  check: {chk.name}{tagstr}{skip}")
            for ln in chk.action.splitlines():
                if ln.strip():
                    lines.append(f"    $ {ln}")
            for a in chk.expects:
                lines.append(f"    expect: {a.raw}"
                             + ("  [INVALID]" if a.kind == "invalid" else ""))
        if c.judged:
            lines.append("  judged (only with --judge):")
            lines += [f"    ? {inv}" for inv in c.judged]
        if c.teardown.strip():
            lines.append("  teardown:")
            lines += [f"    $ {ln}" for ln in c.teardown.splitlines() if ln.strip()]
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
