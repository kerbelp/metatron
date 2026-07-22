"""Render a RunReport as a unit-test-style report: text, JSON, or JUnit XML.

The text report prints a contract's ``## Failure Means`` next to a red check —
the differentiator that routes a failure to the right subsystem.
"""
from __future__ import annotations

import json
from xml.sax.saxutils import escape

from metatron.verification.runner import ContractResult, RunReport


def render_text(report: RunReport) -> str:
    lines: list[str] = []
    for c in report.contracts:
        lines.append(f"{c.slug}  (scope: {c.scope or '-'})")
        if not c.setup_ok:
            lines.append(f"  SETUP FAILED: {c.setup_error}")
        for chk in c.checks:
            if chk.skipped:
                lines.append(f"  SKIP  {chk.name}")
                continue
            mark = "PASS" if chk.passed else "FAIL"
            lines.append(f"  {mark}  {chk.name}")
            if not chk.passed:
                if chk.error:
                    lines.append(f"        {chk.error}")
                for a in chk.assertions:
                    if not a.passed:
                        lines.append(f"        expect: {a.assertion.raw}"
                                     + (f"  ({a.detail})" if a.detail else ""))
        for j in c.judged:
            mark = "PASS" if j.passed else "FAIL"
            lines.append(f"  {mark}? {j.invariant}"
                         + (f"  ({j.note})" if j.note else ""))
        if not c.teardown_ok:
            lines.append("  warning: teardown did not exit cleanly")
        if not c.passed and c.failure_means:
            lines.append("  Failure Means:")
            lines += [f"    - {fm}" for fm in c.failure_means]
        lines.append("")
    status = "PASS" if report.passed else "FAIL"
    lines.append(
        f"{status}: {report.total_checks - report.failed_checks}/"
        f"{report.total_checks} checks passed across {len(report.contracts)} contract(s)"
    )
    return "\n".join(lines)


def render_json(report: RunReport) -> str:
    def contract_obj(c: ContractResult) -> dict:
        return {
            "slug": c.slug,
            "scope": c.scope,
            "passed": c.passed,
            "setup_ok": c.setup_ok,
            "teardown_ok": c.teardown_ok,
            "failure_means": c.failure_means,
            "checks": [
                {
                    "name": chk.name,
                    "passed": chk.passed,
                    "skipped": chk.skipped,
                    "exit_code": chk.exit_code,
                    "error": chk.error,
                    "failed_assertions": [
                        {"expect": a.assertion.raw, "detail": a.detail}
                        for a in chk.assertions if not a.passed
                    ],
                }
                for chk in c.checks
            ],
            "judged": [
                {"invariant": j.invariant, "passed": j.passed, "note": j.note}
                for j in c.judged
            ],
        }

    return json.dumps(
        {
            "passed": report.passed,
            "total_checks": report.total_checks,
            "failed_checks": report.failed_checks,
            "contracts": [contract_obj(c) for c in report.contracts],
        },
        indent=2,
    )


def render_junit(report: RunReport) -> str:
    total = report.total_checks
    failures = report.failed_checks
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<testsuites tests="{total}" failures="{failures}">',
    ]
    for c in report.contracts:
        run = [chk for chk in c.checks if not chk.skipped]
        cfail = sum(1 for chk in run if not chk.passed)
        out.append(
            f'  <testsuite name="{escape(c.slug)}" tests="{len(run)}" '
            f'failures="{cfail}" skipped="{len(c.checks) - len(run)}">'
        )
        for chk in c.checks:
            name = escape(chk.name)
            if chk.skipped:
                out.append(f'    <testcase name="{name}"><skipped/></testcase>')
            elif chk.passed:
                out.append(f'    <testcase name="{name}"/>')
            else:
                detail = chk.error or "; ".join(
                    f"{a.assertion.raw} ({a.detail})"
                    for a in chk.assertions if not a.passed
                )
                if not c.passed and c.failure_means:
                    detail += " | Failure Means: " + "; ".join(c.failure_means)
                out.append(
                    f'    <testcase name="{name}">'
                    f'<failure>{escape(detail)}</failure></testcase>'
                )
        out.append("  </testsuite>")
    out.append("</testsuites>")
    return "\n".join(out)


def render(report: RunReport, fmt: str) -> str:
    return {
        "text": render_text,
        "json": render_json,
        "junit": render_junit,
    }.get(fmt, render_text)(report)
